package org.morphism.srs.portable

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.content.pm.PackageManager
import android.hardware.Camera
import android.os.Bundle
import android.view.SurfaceHolder
import android.view.SurfaceView
import android.widget.FrameLayout
import android.widget.TextView
import android.graphics.Color
import com.google.zxing.BinaryBitmap
import com.google.zxing.PlanarYUVLuminanceSource
import com.google.zxing.common.HybridBinarizer
import com.google.zxing.qrcode.QRCodeReader
import java.util.concurrent.Executors

/** Bundled, offline QR decoding, including devices without Google Play Services. */
@Suppress("DEPRECATION")
class QrScannerActivity: Activity(), SurfaceHolder.Callback {
    private lateinit var preview: SurfaceView
    private lateinit var hint: TextView
    private var camera: Camera?=null
    private var surfaceReady=false
    private val decoder=Executors.newSingleThreadExecutor()
    @Volatile private var decoding=false
    @Volatile private var finished=false
    override fun onCreate(state: Bundle?) {
        super.onCreate(state)
        preview=SurfaceView(this)
        hint=TextView(this).apply { text="Apunta al QR de Morphism en el PC. Atrás para cancelar."; setTextColor(Color.WHITE); setBackgroundColor(0x99000000.toInt()); setPadding(20,20,20,20) }
        setContentView(FrameLayout(this).apply { addView(preview); addView(hint) })
        preview.holder.addCallback(this)
        if(checkSelfPermission(Manifest.permission.CAMERA)!=PackageManager.PERMISSION_GRANTED) requestPermissions(arrayOf(Manifest.permission.CAMERA),1)
    }
    override fun onRequestPermissionsResult(code: Int, permissions: Array<out String>, results: IntArray) {
        super.onRequestPermissionsResult(code,permissions,results)
        if(code==1 && results.firstOrNull()==PackageManager.PERMISSION_GRANTED) startCamera()
        else { setResult(RESULT_CANCELED,Intent().putExtra("error","Permiso de cámara denegado. Puedes pegar la URL.")); finish() }
    }
    override fun surfaceCreated(holder: SurfaceHolder) { surfaceReady=true; startCamera() }
    override fun surfaceChanged(holder: SurfaceHolder,format: Int,width: Int,height: Int) {}
    override fun surfaceDestroyed(holder: SurfaceHolder) { surfaceReady=false; stopCamera() }
    private fun startCamera() {
        if(!surfaceReady || camera!=null || finished || checkSelfPermission(Manifest.permission.CAMERA)!=PackageManager.PERMISSION_GRANTED) return
        try {
            val index=(0 until Camera.getNumberOfCameras()).first { i -> Camera.CameraInfo().also { Camera.getCameraInfo(i,it) }.facing==Camera.CameraInfo.CAMERA_FACING_BACK }
            val device=Camera.open(index); camera=device
            val params=device.parameters
            val size=params.supportedPreviewSizes.filter { it.width<=1280 }.maxByOrNull { it.width*it.height } ?: params.previewSize
            params.setPreviewSize(size.width,size.height)
            if(params.supportedFocusModes.contains(Camera.Parameters.FOCUS_MODE_CONTINUOUS_PICTURE)) params.focusMode=Camera.Parameters.FOCUS_MODE_CONTINUOUS_PICTURE
            device.parameters=params
            val info=Camera.CameraInfo().also { Camera.getCameraInfo(index,it) }
            device.setDisplayOrientation((info.orientation-windowManager.defaultDisplay.rotation*90+360)%360)
            device.setPreviewDisplay(preview.holder)
            device.setPreviewCallback { data, cam ->
                if(data!=null && !decoding && !finished && !decoder.isShutdown) {
                    decoding=true; val frame=data.clone(); val dimensions=cam.parameters.previewSize
                    decoder.execute {
                        try {
                            val source=PlanarYUVLuminanceSource(frame,dimensions.width,dimensions.height,0,0,dimensions.width,dimensions.height,false)
                            val text=QRCodeReader().decode(BinaryBitmap(HybridBinarizer(source))).text
                            if(text.startsWith("morphism-sync://")) {
                                finished=true
                                runOnUiThread { setResult(RESULT_OK,Intent().putExtra("url",text)); finish() }
                            } else runOnUiThread { hint.text="Este QR no es de Morphism. Escanea el del PC." }
                        } catch(_: com.google.zxing.ReaderException) { /* Next camera frame retries. */ }
                        finally { decoding=false }
                    }
                }
            }
            device.startPreview()
        } catch(_: Exception) {
            stopCamera(); setResult(RESULT_CANCELED,Intent().putExtra("error","No se pudo abrir la cámara. Puedes pegar la URL.")); finish()
        }
    }
    private fun stopCamera() {
        val device=camera; camera=null
        if(device!=null) {
            runCatching { device.setPreviewCallback(null); device.stopPreview() }
            runCatching { device.release() }
        }
    }
    override fun onPause() { stopCamera(); super.onPause() }
    override fun onResume() { super.onResume(); startCamera() }
    override fun onDestroy() { finished=true; stopCamera(); decoder.shutdown(); super.onDestroy() }
}
