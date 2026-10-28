# PyInstaller build of wowsyukarinano.exe (one folder, no console). Run build.bat.
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

datas = [("local/assets", "assets")]   # pictures, icon, ship list, default config
datas += collect_data_files("rapidocr_onnxruntime")   # OCR models + config.yaml

a = Analysis(
    ["launcher.py"],
    datas=datas,
    hiddenimports=collect_submodules("rapidocr_onnxruntime") + collect_submodules("dxcam")
    + ["comtypes.stream"],
    excludes=["tkinter", "matplotlib", "IPython", "pytest", "PyQt5", "PySide6", "PySide2"],
)
# Not part of the program: video codecs, software OpenGL, Qt translations and the ffmpeg media backend;
# the PDF, SVG, GIF, TIFF, WebP, ICNS, TGA and WBMP image plugins; touch input; QtNetwork; and the plugin
# platforms used only for offscreen tests. The program shows PNG and JPEG, its icon is an ICO.
DROP = ("opencv_videoio_ffmpeg", "opengl32sw", "ffmpegmediaplugin",
        "/avcodec-", "/avformat-", "/avutil-", "/swresample-", "/swscale-",
        "qt6pdf", "qt6svg", "qt6network", "qt6multimedia",
        "/translations/", "plugins/iconengines/", "plugins/generic/",
        "plugins/imageformats/qgif", "plugins/imageformats/qicns", "plugins/imageformats/qpdf",
        "plugins/imageformats/qsvg", "plugins/imageformats/qtga", "plugins/imageformats/qtiff",
        "plugins/imageformats/qwbmp", "plugins/imageformats/qwebp",
        "plugins/platforms/qminimal", "plugins/platforms/qoffscreen")


def keep(dest):
    path = dest.lower().replace("\\", "/")
    return not any(k in path for k in DROP)


a.binaries = [b for b in a.binaries if keep(b[0])]
a.datas = [d for d in a.datas if keep(d[0])]
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="wowsyukarinano",
    icon="local/assets/icon.ico",
    console=False,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="wowsyukarinano", upx=False)
