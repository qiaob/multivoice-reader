package io.github.qiaob.multivoice

import android.app.Application
import io.github.qiaob.multivoice.data.Library

class MvrApp : Application() {
    override fun onCreate() {
        super.onCreate()
        Library.init(filesDir)
    }
}
