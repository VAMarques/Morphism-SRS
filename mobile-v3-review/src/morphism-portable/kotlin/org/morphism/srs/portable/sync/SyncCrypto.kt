package org.morphism.srs.portable.sync

import java.security.SecureRandom
import javax.crypto.Cipher
import javax.crypto.spec.GCMParameterSpec
import javax.crypto.spec.SecretKeySpec

object SyncCrypto {
    fun seal(key: ByteArray, plain: ByteArray, aad: ByteArray): ByteArray {
        val nonce=ByteArray(12).also { SecureRandom().nextBytes(it) }
        val cipher=Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE,SecretKeySpec(key,"AES"),GCMParameterSpec(128,nonce))
        cipher.updateAAD(aad)
        return nonce+cipher.doFinal(plain)
    }
    fun open(key: ByteArray, sealed: ByteArray, aad: ByteArray): ByteArray {
        require(sealed.size>=28) { "Respuesta cifrada incompleta" }
        val cipher=Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.DECRYPT_MODE,SecretKeySpec(key,"AES"),GCMParameterSpec(128,sealed.copyOfRange(0,12)))
        cipher.updateAAD(aad)
        return cipher.doFinal(sealed.copyOfRange(12,sealed.size))
    }
}
