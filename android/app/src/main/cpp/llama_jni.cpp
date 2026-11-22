// The labelling model on the phone: one llama.cpp model with the fine-tuned LoRA adapter,
// which is put on to label lines and taken off to judge a new character's gender and age.
// Answers are greedy, as mlx_lm.generate gives them on the Mac.

#include <jni.h>
#include <android/log.h>

#include <algorithm>
#include <chrono>
#include <string>
#include <vector>

#include "llama.h"

#define LOG(...) __android_log_print(ANDROID_LOG_INFO, "mvr_llama", __VA_ARGS__)

namespace {

struct Engine {
    llama_model * model = nullptr;
    llama_context * ctx = nullptr;
    llama_adapter_lora * adapter = nullptr;
    llama_sampler * sampler = nullptr;
    int64_t prompt_tokens = 0, made_tokens = 0, prompt_us = 0, made_us = 0;
};

int64_t now_us() {
    return std::chrono::duration_cast<std::chrono::microseconds>(
               std::chrono::steady_clock::now().time_since_epoch()).count();
}

std::string str(JNIEnv * env, jstring s) {
    const char * c = env->GetStringUTFChars(s, nullptr);
    std::string out(c);
    env->ReleaseStringUTFChars(s, c);
    return out;
}

void fail(JNIEnv * env, const std::string & message) {
    env->ThrowNew(env->FindClass("java/lang/IllegalStateException"), message.c_str());
}

void close(Engine * e) {
    if (e->sampler) llama_sampler_free(e->sampler);
    if (e->ctx) llama_free(e->ctx);
    if (e->model) llama_model_free(e->model);  // frees the adapter with it
    delete e;
}

// Java strings are modified UTF-8; hand back real UTF-8 bytes as a String via new String(bytes, UTF_8).
jstring utf8(JNIEnv * env, const std::string & s) {
    jbyteArray bytes = env->NewByteArray((jsize) s.size());
    env->SetByteArrayRegion(bytes, 0, (jsize) s.size(), (const jbyte *) s.data());
    jclass string_class = env->FindClass("java/lang/String");
    jmethodID init = env->GetMethodID(string_class, "<init>", "([BLjava/lang/String;)V");
    return (jstring) env->NewObject(string_class, init, bytes, env->NewStringUTF("UTF-8"));
}

}  // namespace

extern "C" JNIEXPORT jlong JNICALL
Java_io_github_qiaob_multivoice_llm_Llama_nativeLoad(
        JNIEnv * env, jclass, jstring model_path, jstring adapter_path, jint n_ctx, jint n_threads) {
    static bool started = false;
    if (!started) {
        llama_backend_init();
        started = true;
    }
    auto * e = new Engine();
    llama_model_params mp = llama_model_default_params();
    mp.n_gpu_layers = 0;
    e->model = llama_model_load_from_file(str(env, model_path).c_str(), mp);
    if (!e->model) {
        close(e);
        fail(env, "模型文件读不出来，可能没下载完整，或者不是 GGUF 格式");
        return 0;
    }
    std::string adapter = str(env, adapter_path);
    if (!adapter.empty()) {
        e->adapter = llama_adapter_lora_init(e->model, adapter.c_str());
        if (!e->adapter) {
            close(e);
            fail(env, "微调权重和这个模型对不上：底座模型下错了？");
            return 0;
        }
    }
    llama_context_params cp = llama_context_default_params();
    cp.n_ctx = n_ctx;
    cp.n_batch = 1024;
    cp.n_ubatch = 512;
    cp.n_threads = n_threads;
    cp.n_threads_batch = n_threads;
    e->ctx = llama_init_from_model(e->model, cp);
    if (!e->ctx) {
        close(e);
        fail(env, "内存不够，建不起推理上下文");
        return 0;
    }
    e->sampler = llama_sampler_init_greedy();
    return (jlong) e;
}

extern "C" JNIEXPORT void JNICALL
Java_io_github_qiaob_multivoice_llm_Llama_nativeFree(JNIEnv *, jclass, jlong handle) {
    if (handle) close((Engine *) handle);
}

extern "C" JNIEXPORT jstring JNICALL
Java_io_github_qiaob_multivoice_llm_Llama_nativeChatTemplate(JNIEnv * env, jclass, jlong handle) {
    const char * t = llama_model_chat_template(((Engine *) handle)->model, nullptr);
    return utf8(env, t ? t : "");
}

// `text` is the whole prompt as the chat template lays it out; the answer comes back without
// the token that ends it.
extern "C" JNIEXPORT jstring JNICALL
Java_io_github_qiaob_multivoice_llm_Llama_nativeAsk(
        JNIEnv * env, jclass, jlong handle, jbyteArray text_bytes, jint max_tokens, jboolean tuned) {
    auto * e = (Engine *) handle;
    std::string text(env->GetArrayLength(text_bytes), '\0');
    env->GetByteArrayRegion(text_bytes, 0, (jsize) text.size(), (jbyte *) text.data());

    if (e->adapter && tuned) {
        float scale = 1.0f;  // llama.cpp applies alpha / rank itself, as PEFT does
        llama_set_adapters_lora(e->ctx, &e->adapter, 1, &scale);
    } else {
        llama_set_adapters_lora(e->ctx, nullptr, 0, nullptr);
    }
    llama_memory_clear(llama_get_memory(e->ctx), true);
    llama_sampler_reset(e->sampler);

    const llama_vocab * vocab = llama_model_get_vocab(e->model);
    int n = -llama_tokenize(vocab, text.c_str(), (int32_t) text.size(), nullptr, 0, false, true);
    std::vector<llama_token> tokens(n);
    llama_tokenize(vocab, text.c_str(), (int32_t) text.size(), tokens.data(), n, false, true);
    if (n + max_tokens > (int) llama_n_ctx(e->ctx)) {
        fail(env, "这段文字太长，放不进模型的上下文");
        return nullptr;
    }

    int64_t start = now_us();
    const int batch = (int) llama_n_batch(e->ctx);
    for (int at = 0; at < n; at += batch) {
        int count = std::min(batch, n - at);
        if (llama_decode(e->ctx, llama_batch_get_one(tokens.data() + at, count)) != 0) {
            fail(env, "模型读提示时出错");
            return nullptr;
        }
    }
    int64_t read = now_us();

    std::string answer;
    int made = 0;
    char piece[256];
    for (; made < max_tokens; made++) {
        llama_token token = llama_sampler_sample(e->sampler, e->ctx, -1);
        if (llama_vocab_is_eog(vocab, token)) break;
        int len = llama_token_to_piece(vocab, token, piece, sizeof(piece), 0, false);
        if (len > 0) answer.append(piece, len);
        if (llama_decode(e->ctx, llama_batch_get_one(&token, 1)) != 0) {
            fail(env, "模型生成回答时出错");
            return nullptr;
        }
    }
    int64_t end = now_us();
    e->prompt_tokens += n;
    e->made_tokens += made;
    e->prompt_us += read - start;
    e->made_us += end - read;
    return utf8(env, answer);
}

// Totals since the model was loaded: prompt tokens, answer tokens, and microseconds for each.
extern "C" JNIEXPORT jlongArray JNICALL
Java_io_github_qiaob_multivoice_llm_Llama_nativeStats(JNIEnv * env, jclass, jlong handle) {
    auto * e = (Engine *) handle;
    jlong values[4] = {e->prompt_tokens, e->made_tokens, e->prompt_us, e->made_us};
    jlongArray out = env->NewLongArray(4);
    env->SetLongArrayRegion(out, 0, 4, values);
    return out;
}
