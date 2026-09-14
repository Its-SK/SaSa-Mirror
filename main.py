import sys
import os
import time
import traceback
import threading
import queue
import platform

# ------------------------------------------------------------
# CRITICAL FIX FOR --noconsole .EXE CRASHES
# ------------------------------------------------------------
class DummyOutput:
    def write(self, x): pass
    def flush(self): pass
if sys.stdout is None: sys.stdout = DummyOutput()
if sys.stderr is None: sys.stderr = DummyOutput()

import av
import cv2
import libusb_package
import numpy as np
import usb.core
import usb.util
import sounddevice as sd

# ------------------------------------------------------------
# Windows DPI, Resolution & Native Mouse Polling Hooks
# ------------------------------------------------------------
try:
    import ctypes
    import ctypes.wintypes
    ctypes.windll.user32.SetProcessDPIAware()
    SCREEN_W = ctypes.windll.user32.GetSystemMetrics(0)
    SCREEN_H = ctypes.windll.user32.GetSystemMetrics(1)
    IS_WINDOWS = True
except Exception:
    SCREEN_W, SCREEN_H = 1920, 1080 
    IS_WINDOWS = False

# ============================================================
# APP CONFIGURATION & STATE
# ============================================================
APP_NAME = "SaSa Mirror"

MANUFACTURER = "SamimStreams"
MODEL = "ZeroLagMirror"
DESCRIPTION = "AOA Screen Mirror"
VERSION = "1.0"
URI = "https://github.com/samim"
SERIAL = "123456"

AOA_PRODUCT_IDS = {0x2D00, 0x2D01, 0x2D02, 0x2D03, 0x2D04, 0x2D05}
IGNORED_VENDORS = {0x8086, 0x1022, 0x045E, 0x0BDA, 0x1D6B, 0x046D, 0x0408, 0x0E8D}

UI_STATE = {
    "view": "waiting",
    "hover": None,
    "hitboxes": {},
    "settings": {
        "show_fps": True
    },
    "temp_settings": {
        "show_fps": True
    }
}

PREV_LBUTTON_DOWN = False
ICON_SUCCESSFULLY_SET = False

# ============================================================
# WINDOWS TITLE BAR ICON & CURSOR FIX
# ============================================================

def set_window_icon(icon_filename="icon.ico"):
    """ 
    Injects a custom .ico file into the OpenCV Title bar and Windows Taskbar. 
    It will keep trying until the OpenCV window is fully initialized.
    """
    global ICON_SUCCESSFULLY_SET
    if not IS_WINDOWS or ICON_SUCCESSFULLY_SET:
        return
    
    try:
        # Force Windows to group this app properly in the Taskbar
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("samim.sasamirror.1.0")
    except Exception:
        pass
    
    if getattr(sys, 'frozen', False):
        application_path = sys._MEIPASS
    else:
        application_path = os.path.dirname(os.path.abspath(__file__))
        
    icon_path = os.path.join(application_path, icon_filename)
    
    if not os.path.exists(icon_path):
        return

    try:
        # Prevent 64-bit handle truncation
        FindWindowW = ctypes.windll.user32.FindWindowW
        FindWindowW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
        FindWindowW.restype = ctypes.c_void_p
        
        LoadImageW = ctypes.windll.user32.LoadImageW
        LoadImageW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
        LoadImageW.restype = ctypes.c_void_p
        
        SendMessageW = ctypes.windll.user32.SendMessageW
        SendMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p]
        SendMessageW.restype = ctypes.c_void_p

        # We must wait until cv2.imshow has actually created the HWND
        hwnd = FindWindowW(None, APP_NAME)
        if hwnd:
            WM_SETICON = 0x80
            ICON_SMALL = 0
            ICON_BIG = 1
            LR_LOADFROMFILE = 0x0010
            IMAGE_ICON = 1
            
            hicon = LoadImageW(None, icon_path, IMAGE_ICON, 0, 0, LR_LOADFROMFILE)
            if hicon:
                SendMessageW(hwnd, WM_SETICON, ICON_SMALL, hicon)
                SendMessageW(hwnd, WM_SETICON, ICON_BIG, hicon)
                ICON_SUCCESSFULLY_SET = True # Lock it so we don't spam the OS
    except Exception:
        pass

def fix_opencv_cursor():
    if not IS_WINDOWS:
        return
    
    try:
        # Prevent 64-bit handle truncation
        FindWindowW = ctypes.windll.user32.FindWindowW
        FindWindowW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
        FindWindowW.restype = ctypes.c_void_p
        
        hwnd = FindWindowW(None, APP_NAME)
        if not hwnd:
            return

        LoadCursorW = ctypes.windll.user32.LoadCursorW
        LoadCursorW.argtypes = [ctypes.c_void_p, ctypes.c_int]
        LoadCursorW.restype = ctypes.c_void_p

        arrow_cursor = LoadCursorW(None, 32512)
        
        if platform.architecture()[0] == '32bit':
            SetClassLong = ctypes.windll.user32.SetClassLongW
        else:
            SetClassLong = ctypes.windll.user32.SetClassLongPtrW
            
        SetClassLong.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
        SetClassLong.restype = ctypes.c_void_p
        
        SetClassLong(hwnd, -12, arrow_cursor)

        GetWindow = ctypes.windll.user32.GetWindow
        GetWindow.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        GetWindow.restype = ctypes.c_void_p
        
        child_hwnd = GetWindow(hwnd, 5) # GW_CHILD
        if child_hwnd:
            SetClassLong(child_hwnd, -12, arrow_cursor)

    except Exception:
        pass
# ============================================================
# USB / AOA HELPERS
# ============================================================

def safe_usb_cleanup(dev):
    if dev is not None:
        try: usb.util.dispose_resources(dev)
        except Exception: pass

def send_aoa_string(dev, index, value):
    try:
        data = value.encode("utf-8") + b"\x00"
        dev.ctrl_transfer(0x40, 52, 0, index, data)
        return True
    except Exception: return False

def find_active_aoa_device():
    try:
        for dev in libusb_package.find(find_all=True):
            try:
                if int(dev.idProduct) in AOA_PRODUCT_IDS: return dev
            except Exception: continue
    except Exception: pass
    return None

def request_aoa_mode(dev):
    try:
        vid, pid = int(dev.idVendor), int(dev.idProduct)
        if vid in IGNORED_VENDORS: return False
        response = dev.ctrl_transfer(0xC0, 51, 0, 0, 2)
        if response is None or len(response) < 2: return False

        strings = [(0, MANUFACTURER), (1, MODEL), (2, DESCRIPTION), (3, VERSION), (4, URI), (5, SERIAL)]
        for index, value in strings:
            if not send_aoa_string(dev, index, value): return False

        dev.ctrl_transfer(0x40, 53, 0, 0, 0)
        return True
    except Exception: return False

def probe_and_handshake_all_devices():
    try: devices = list(libusb_package.find(find_all=True))
    except Exception: return False
    for dev in devices:
        if request_aoa_mode(dev): return True
    return False

def find_bulk_in_endpoint(dev):
    try:
        try: cfg = dev.get_active_configuration()
        except usb.core.USBError:
            dev.set_configuration()
            cfg = dev.get_active_configuration()

        for intf in cfg:
            for ep in intf:
                try:
                    if (usb.util.endpoint_direction(ep.bEndpointAddress) == usb.util.ENDPOINT_IN and 
                        usb.util.endpoint_type(ep.bmAttributes) == usb.util.ENDPOINT_TYPE_BULK):
                        return intf, ep
                except Exception: continue
    except Exception: pass
    return None, None


# ------------------------------------------------------------
# Smart Letterboxing & Window Hooks
# ------------------------------------------------------------

def apply_letterbox(img, target_w, target_h):
    h, w = img.shape[:2]
    if target_w <= 0 or target_h <= 0 or w <= 0 or h <= 0:
        return img
        
    scale = min(target_w / w, target_h / h)
    new_w = int(w * scale)
    new_h = int(h * scale)
    
    if new_w <= 0 or new_h <= 0:
        return img
        
    resized = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
    canvas = np.zeros((target_h, target_w, 3), dtype=np.uint8)
    
    y_off = (target_h - new_h) // 2
    x_off = (target_w - new_w) // 2
    
    canvas[y_off:y_off+new_h, x_off:x_off+new_w] = resized
    return canvas

def check_maximize_click(app_state):
    if not IS_WINDOWS: return
    try:
        hwnd = ctypes.windll.user32.FindWindowW(None, APP_NAME)
        if hwnd and ctypes.windll.user32.IsZoomed(hwnd):
            ctypes.windll.user32.ShowWindow(hwnd, 9) 
            app_state["fullscreen"] = True
            cv2.setWindowProperty(APP_NAME, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
    except Exception: pass

def check_window_closed():
    """ Detects if the user clicked the 'X' button to close the app. """
    try:
        return cv2.getWindowProperty(APP_NAME, cv2.WND_PROP_VISIBLE) < 1
    except Exception:
        return True


# ============================================================
# NATIVE WINDOWS MOUSE POLLING
# ============================================================

def poll_mouse_events():
    global PREV_LBUTTON_DOWN
    if not IS_WINDOWS or UI_STATE["view"] == "streaming":
        return

    try:
        hwnd = ctypes.windll.user32.FindWindowW(None, APP_NAME)
        if not hwnd or ctypes.windll.user32.GetForegroundWindow() != hwnd:
            UI_STATE["hover"] = None
            return

        pt = ctypes.wintypes.POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
        ctypes.windll.user32.ScreenToClient(hwnd, ctypes.byref(pt))
        x, y = pt.x, pt.y

        hovered = None
        for name, (x1, y1, x2, y2) in UI_STATE["hitboxes"].items():
            if x1 <= x <= x2 and y1 <= y <= y2:
                hovered = name
                break
        UI_STATE["hover"] = hovered

        is_down = (ctypes.windll.user32.GetAsyncKeyState(0x01) & 0x8000) != 0
        if is_down and not PREV_LBUTTON_DOWN:
            if hovered == "settings_btn":
                UI_STATE["temp_settings"]["show_fps"] = UI_STATE["settings"]["show_fps"]
                UI_STATE["view"] = "settings"
            elif hovered == "fps_checkbox":
                UI_STATE["temp_settings"]["show_fps"] = not UI_STATE["temp_settings"]["show_fps"]
            elif hovered == "apply_btn":
                UI_STATE["settings"]["show_fps"] = UI_STATE["temp_settings"]["show_fps"]
            elif hovered == "save_btn":
                UI_STATE["settings"]["show_fps"] = UI_STATE["temp_settings"]["show_fps"]
                UI_STATE["view"] = "waiting"

        PREV_LBUTTON_DOWN = is_down
    except Exception:
        pass


# ============================================================
# UI SCREENS
# ============================================================

def render_waiting_screen(w, h):
    canvas = np.zeros((h, w, 3), dtype=np.uint8)
    hitboxes = {}
    
    cv2.putText(canvas, "STATUS: WAITING FOR ANDROID DEVICE...", (60, h//2 - 50), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2, cv2.LINE_AA)
    cv2.putText(canvas, "Connect Android device with USB.", (60, h//2 + 5), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (220, 220, 220), 2, cv2.LINE_AA)
    cv2.putText(canvas, "F / Maximize = Fullscreen | Esc = Exit Fullscreen", (60, h//2 + 50), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (180, 180, 180), 2, cv2.LINE_AA)
    
    btn_w, btn_h = 130, 40
    btn_x, btn_y = w - btn_w - 20, 20
    hitboxes["settings_btn"] = (btn_x, btn_y, btn_x + btn_w, btn_y + btn_h)
    
    color = (120, 120, 120) if UI_STATE["hover"] == "settings_btn" else (80, 80, 80)
    cv2.rectangle(canvas, (btn_x, btn_y), (btn_x + btn_w, btn_y + btn_h), color, -1)
    cv2.putText(canvas, "Settings", (btn_x + 20, btn_y + 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2, cv2.LINE_AA)
    
    return canvas, hitboxes


def render_settings_screen(w, h):
    canvas = np.zeros((h, w, 3), dtype=np.uint8)
    canvas[:] = (35, 35, 35)
    hitboxes = {}
    
    cv2.putText(canvas, f"{APP_NAME} Settings", (50, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (255, 255, 255), 2, cv2.LINE_AA)
    cv2.line(canvas, (50, 80), (w - 50, 80), (100, 100, 100), 2)
    
    cv2.putText(canvas, "Show FPS Overlay", (50, 150), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (220, 220, 220), 2, cv2.LINE_AA)
    
    cb_x, cb_y, cb_w, cb_h = 350, 122, 30, 30
    hitboxes["fps_checkbox"] = (cb_x, cb_y, cb_x + cb_w, cb_y + cb_h)
    
    cv2.rectangle(canvas, (cb_x, cb_y), (cb_x + cb_w, cb_y + cb_h), (200, 200, 200), 2)
    if UI_STATE["temp_settings"]["show_fps"]:
        cv2.line(canvas, (cb_x + 5, cb_y + 15), (cb_x + 12, cb_y + cb_h - 5), (0, 255, 0), 3, cv2.LINE_AA)
        cv2.line(canvas, (cb_x + 12, cb_y + cb_h - 5), (cb_x + cb_w - 5, cb_y + 5), (0, 255, 0), 3, cv2.LINE_AA)

    save_w, save_h = 120, 40
    save_x, save_y = w - save_w - 50, h - save_h - 50
    hitboxes["save_btn"] = (save_x, save_y, save_x + save_w, save_y + save_h)
    
    apply_w, apply_h = 120, 40
    apply_x, apply_y = save_x - apply_w - 20, save_y
    hitboxes["apply_btn"] = (apply_x, apply_y, apply_x + apply_w, apply_y + apply_h)
    
    app_color = (120, 120, 120) if UI_STATE["hover"] == "apply_btn" else (80, 80, 80)
    cv2.rectangle(canvas, (apply_x, apply_y), (apply_x + apply_w, apply_y + apply_h), app_color, -1)
    cv2.putText(canvas, "Apply", (apply_x + 25, apply_y + 28), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2, cv2.LINE_AA)
    
    sav_color = (120, 120, 120) if UI_STATE["hover"] == "save_btn" else (80, 80, 80)
    cv2.rectangle(canvas, (save_x, save_y), (save_x + save_w, save_y + save_h), sav_color, -1)
    cv2.putText(canvas, "Save", (save_x + 35, save_y + 28), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2, cv2.LINE_AA)
    
    return canvas, hitboxes

# ============================================================
# MULTIPLEXED A/V STREAM
# ============================================================

def run_stream(dev, app_state):
    UI_STATE["view"] = "streaming"
    UI_STATE["hitboxes"] = {}

    intf, ep_in = find_bulk_in_endpoint(dev)
    if intf is None or ep_in is None:
        UI_STATE["view"] = "waiting"
        return

    try: usb.util.claim_interface(dev, intf.bInterfaceNumber)
    except Exception: pass

    is_streaming = [True] 
    video_queue = queue.Queue(maxsize=15)
    audio_queue = queue.Queue(maxsize=15)

    def usb_reader_worker():
        stream_buffer = bytearray()
        while is_streaming[0]:
            try:
                usb_data = ep_in.read(1024 * 1024, timeout=500)
                if not usb_data: continue
                stream_buffer.extend(usb_data)

                while True:
                    if len(stream_buffer) < 5: break
                    payload_type = stream_buffer[0]
                    payload_length = int.from_bytes(stream_buffer[1:5], byteorder='big')
                    
                    if len(stream_buffer) < 5 + payload_length: break 
                    
                    payload = bytes(stream_buffer[5:5+payload_length])
                    del stream_buffer[:5+payload_length]

                    if payload_type == 1:
                        if video_queue.full():
                            try: video_queue.get_nowait()
                            except queue.Empty: pass
                        video_queue.put_nowait(payload)
                        
                    elif payload_type == 2:
                        if audio_queue.full():
                            try: audio_queue.get_nowait()
                            except queue.Empty: pass
                        audio_queue.put_nowait(payload)

            except usb.core.USBError as e:
                if getattr(e, "errno", None) in (10060, 110, 116) or "timeout" in str(e).lower():
                    continue 
                is_streaming[0] = False
                break
            except Exception:
                is_streaming[0] = False
                break

    audio_stream = None
    try:
        audio_stream = sd.RawOutputStream(samplerate=48000, channels=2, dtype='int16', latency='low')
        audio_stream.start()
    except Exception:
        pass

    def audio_worker():
        while is_streaming[0]:
            try:
                payload = audio_queue.get(timeout=0.1)
                if audio_stream is not None:
                    audio_stream.write(payload)
            except queue.Empty: continue
            except Exception: pass

    threading.Thread(target=usb_reader_worker, daemon=True).start()
    threading.Thread(target=audio_worker, daemon=True).start()

    try:
        codec = av.CodecContext.create("h264", "r")
        rotation_state = 0
        
        fps_start_time = time.time()
        fps_frames = 0
        current_fps = 0.0
        
        while is_streaming[0]:
            if check_window_closed():
                is_streaming[0] = False
                sys.exit(0)

            check_maximize_click(app_state)
            set_window_icon("icon.ico")
            fix_opencv_cursor()
            
            try:
                payload = video_queue.get(timeout=0.1)
                packets = codec.parse(payload)
                for packet in packets:
                    frames = codec.decode(packet)
                    for frame in frames:
                        try: img = frame.to_ndarray(format="bgr24")
                        except Exception: continue

                        fps_frames += 1
                        now = time.time()
                        elapsed = now - fps_start_time
                        if elapsed >= 1.0:
                            current_fps = fps_frames / elapsed
                            fps_frames = 0
                            fps_start_time = now

                        if rotation_state == 1: img = cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
                        elif rotation_state == 2: img = cv2.rotate(img, cv2.ROTATE_180)
                        elif rotation_state == 3: img = cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)

                        if UI_STATE["settings"]["show_fps"]:
                            fps_text = f"FPS: {int(current_fps)}"
                            cv2.putText(img, fps_text, (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 4, cv2.LINE_AA)
                            cv2.putText(img, fps_text, (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 2, cv2.LINE_AA)

                        target_w, target_h = 1280, 720
                        if app_state["fullscreen"]:
                            target_w, target_h = SCREEN_W, SCREEN_H
                        else:
                            try:
                                rect = cv2.getWindowImageRect(APP_NAME)
                                if rect[2] > 0 and rect[3] > 0:
                                    target_w, target_h = rect[2], rect[3]
                            except Exception: pass

                        img_to_show = apply_letterbox(img, target_w, target_h)
                        cv2.imshow(APP_NAME, img_to_show)

            except queue.Empty: pass 
            except Exception: pass 

            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                is_streaming[0] = False
                break
            elif key == ord("r"):
                rotation_state = (rotation_state + 1) % 4
            elif key == ord("f"):
                app_state["fullscreen"] = not app_state["fullscreen"]
                if app_state["fullscreen"]:
                    cv2.setWindowProperty(APP_NAME, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
                else:
                    cv2.setWindowProperty(APP_NAME, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_NORMAL)
            elif key == 27: 
                if app_state["fullscreen"]:
                    app_state["fullscreen"] = False
                    cv2.setWindowProperty(APP_NAME, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_NORMAL)

    finally:
        UI_STATE["view"] = "waiting" 
        is_streaming[0] = False 
        
        if audio_stream is not None:
            audio_stream.stop()
            audio_stream.close()
        if intf is not None:
            try: usb.util.release_interface(dev, intf.bInterfaceNumber)
            except Exception: pass
        safe_usb_cleanup(dev)

# ============================================================
# MAIN
# ============================================================

def main():
    cv2.namedWindow(APP_NAME, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(APP_NAME, 1280, 720)

    app_state = {"fullscreen": False}
    last_poll_time = 0

    while True:
        try:
            if check_window_closed():
                break

            poll_mouse_events()

            if UI_STATE["view"] == "waiting":
                now = time.time()
                if now - last_poll_time >= 1.5:
                    last_poll_time = now

                    aoa_dev = find_active_aoa_device()
                    if aoa_dev is not None:
                        run_stream(aoa_dev, app_state)
                        continue

                    probe_and_handshake_all_devices()

            check_maximize_click(app_state)
            target_w, target_h = 1280, 720
            
            if app_state["fullscreen"]:
                target_w, target_h = SCREEN_W, SCREEN_H
            else:
                try:
                    rect = cv2.getWindowImageRect(APP_NAME)
                    if rect[2] > 0 and rect[3] > 0:
                        target_w, target_h = rect[2], rect[3]
                except Exception: pass

            if UI_STATE["view"] == "waiting":
                display_ui, hitboxes = render_waiting_screen(max(640, target_w), max(480, target_h))
                UI_STATE["hitboxes"] = hitboxes
                cv2.imshow(APP_NAME, display_ui)
                
            elif UI_STATE["view"] == "settings":
                display_ui, hitboxes = render_settings_screen(max(640, target_w), max(480, target_h))
                UI_STATE["hitboxes"] = hitboxes
                cv2.imshow(APP_NAME, display_ui)

            # Keep firing the icon injector and cursor fix while the UI loop is active
            set_window_icon("icon.ico")
            fix_opencv_cursor()

            key = cv2.waitKey(10) & 0xFF
            if key == ord("q"):
                break
            elif key == ord("f"):
                app_state["fullscreen"] = not app_state["fullscreen"]
                if app_state["fullscreen"]:
                    cv2.setWindowProperty(APP_NAME, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
                else:
                    cv2.setWindowProperty(APP_NAME, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_NORMAL)
            elif key == 27: 
                if app_state["fullscreen"]:
                    app_state["fullscreen"] = False
                    cv2.setWindowProperty(APP_NAME, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_NORMAL)

        except KeyboardInterrupt:
            break
        except Exception:
            time.sleep(1)

    cv2.destroyAllWindows()
    sys.exit(0)

if __name__ == "__main__":
    main()