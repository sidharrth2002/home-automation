package com.sid.home.ui

import android.content.Context
import coil.imageLoader
import coil.request.CachePolicy
import coil.request.ImageRequest
import com.sid.home.ha.HomeState
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.launch
import kotlinx.serialization.json.jsonObject

/**
 * Keeps every photo in the frame on the TV's disk (Coil's cache), fetched as soon as the list arrives, so the
 * slideshow and screensaver carry on with the Mac off.
 */
object PhotoCache {
    /** Whether a photo is on the TV's disk (so it can show with the Mac off). */
    @OptIn(coil.annotation.ExperimentalCoilApi::class)
    fun isCached(context: Context, url: String): Boolean =
        runCatching { context.imageLoader.diskCache?.openSnapshot(url)?.use { true } ?: false }.getOrDefault(false)

    fun keepWarm(context: Context, home: HomeState, scope: CoroutineScope) = scope.launch {
        home.entities.map { it[Ids2.PHOTOS]?.arr("photos")?.mapNotNull { p -> photoUrl(p.jsonObject) } ?: emptyList() }
            .distinctUntilChanged().collect { urls ->
                // the disk cache keeps the downloaded file, so decode it tiny: only the download is wanted here
                // (at the default size each one was a throwaway full-screen bitmap, ~8 MB, one after another)
                for (u in urls) context.imageLoader.enqueue(ImageRequest.Builder(context).data(u).size(16, 16)
                    .memoryCachePolicy(CachePolicy.DISABLED).diskCachePolicy(CachePolicy.ENABLED).build())
            }
    }
}

