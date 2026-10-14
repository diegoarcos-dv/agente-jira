# Modelos TTS locales

Los binarios `.onnx` y `.onnx.json` no se versionan. En Linux, después de instalar las
dependencias, descarga explícitamente la voz española mexicana con:

```bash
bash scripts/setup-piper-voice.sh
```

La descarga se realiza una sola vez durante la preparación del servidor. En ejecución, Piper
carga ambos archivos desde este directorio y no envía texto ni audio a Internet.
