// Compile each regular expression in a file (one per line) with ICU, the engine behind
// Android's java.util.regex, and say which ones it refuses.
//   cc tools/check_icu_regex.c -licuuc -licui18n -o build/check_icu_regex
//   ./gradlew :core:test && build/check_icu_regex core/build/regex-patterns.txt
#include <stdio.h>
#include <string.h>
#include <unicode/uregex.h>

int main(int argc, char ** argv) {
    FILE * f = fopen(argv[1], "r");
    char line[8192];
    int bad = 0, n = 0;
    while (fgets(line, sizeof line, f)) {
        line[strcspn(line, "\n")] = 0;
        UErrorCode status = U_ZERO_ERROR;
        UParseError where;
        URegularExpression * re = uregex_openC(line, 0, &where, &status);
        n++;
        if (U_FAILURE(status)) {
            printf("ICU refuses (%s at %d): %s\n", u_errorName(status), where.offset, line);
            bad++;
        }
        if (re) uregex_close(re);
    }
    printf("%d patterns, %d refused\n", n, bad);
    return bad != 0;
}
