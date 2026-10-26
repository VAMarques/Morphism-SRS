package org.morphism.srs.portable.sync

import android.content.Context
import org.json.JSONArray
import java.io.File
import java.security.MessageDigest

class MediaSyncStore(context: Context) {
    val directory=File(context.filesDir,"media").apply { mkdirs() }
    fun synchronize(manifest: JSONArray, fetch: (String) -> ByteArray) {
        for(i in 0 until manifest.length()) {
            val asset=manifest.getJSONObject(i); val hash=asset.getString("sha256_hash")
            require(hash.matches(Regex("[0-9a-f]{64}")))
            val originalExt=asset.getString("original_name").substringAfterLast('.',"").lowercase()
            val ext=if(originalExt in listOf("svg","png","jpg","jpeg","gif","webp")) originalExt else extension(asset.getString("mime_type"))
            val name="$hash.$ext"; val target=File(directory,name)
            if(target.isFile && digest(target.readBytes())==hash) continue
            val bytes=fetch("/media/$name")
            require(digest(bytes)==hash && bytes.size.toLong()==asset.getLong("byte_size")) { "Media corrupto: $name" }
            val temp=File(directory,"$name.part")
            temp.outputStream().use { it.write(bytes) }
            check(temp.renameTo(target)) { "No se pudo guardar $name" }
        }
    }
    companion object {
        fun extension(mime: String)=when(mime) { "image/svg+xml"->"svg"; "image/jpeg"->"jpg"; "image/webp"->"webp"; "image/gif"->"gif"; else->"png" }
        fun digest(bytes: ByteArray)=MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }
    }
}
