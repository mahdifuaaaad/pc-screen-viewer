import os
import json
import time
import socket
import threading
from datetime import datetime
import requests
import flet as ft

# ==============================================================================
# 1. إدارة البيانات المحفوظة وإعدادات الموبايل (Client Storage Manager)
# ==============================================================================

STORAGE_FILE = "mobile_saved_devices.json"

DEFAULT_CLIENT_DATA = {
    "viewer_name": "موبايل أمي",
    "auto_connect_last": False,
    "last_connected_ip": "",
    "theme_mode": "dark",
    "default_fit": "CONTAIN",       # CONTAIN, COVER, FILL
    "max_zoom_scale": 5.0,
    "show_pc_telemetry": True,
    "saved_devices": []
}


class ClientStorage:
    def __init__(self):
        self.data = self.load()

    def load(self):
        if os.path.exists(STORAGE_FILE):
            try:
                with open(STORAGE_FILE, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                    merged = DEFAULT_CLIENT_DATA.copy()
                    merged.update(loaded)
                    return merged
            except Exception:
                pass
        return DEFAULT_CLIENT_DATA.copy()

    def save(self):
        try:
            with open(STORAGE_FILE, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"Error saving client data: {e}")

    def upsert_device(self, name, ip, port=5000, pin="", favorite=False):
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        devices = self.data.get("saved_devices", [])
        found = False
        for dev in devices:
            if dev["ip"] == ip and int(dev.get("port", 5000)) == int(port):
                dev["name"] = name or dev["name"]
                dev["pin"] = pin
                dev["last_connected"] = now_str
                found = True
                break

        if not found:
            devices.insert(0, {
                "name": name or f"حاسبة ({ip})",
                "ip": ip,
                "port": int(port),
                "pin": pin,
                "favorite": favorite,
                "last_connected": now_str
            })

        devices.sort(key=lambda x: (not x.get("favorite", False), x.get("last_connected", "")), reverse=False)
        self.data["saved_devices"] = devices
        self.data["last_connected_ip"] = ip
        self.save()

    def delete_device(self, ip):
        self.data["saved_devices"] = [d for d in self.data["saved_devices"] if d["ip"] != ip]
        self.save()

    def toggle_favorite(self, ip):
        for dev in self.data["saved_devices"]:
            if dev["ip"] == ip:
                dev["favorite"] = not dev.get("favorite", False)
                break
        self.save()


storage = ClientStorage()

# ==============================================================================
# 2. رادار البحث التلقائي عن الحاسبات في الشبكة (UDP Scanner)
# ==============================================================================

def discover_lan_servers(timeout=2.0):
    discovered = {}
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.settimeout(0.4)

    try:
        sock.sendto(b"DISCOVER_PC_SERVERS", ("<broadcast>", 5001))
    except Exception:
        pass

    start_t = time.time()
    while time.time() - start_t < timeout:
        try:
            data, addr = sock.recvfrom(2048)
            payload = json.loads(data.decode("utf-8"))
            if payload.get("type") == "SCREEN_SERVER_BEACON":
                ip = payload.get("ip") or addr[0]
                discovered[ip] = {
                    "name": payload.get("name", f"حاسبة ({ip})"),
                    "ip": ip,
                    "port": payload.get("port", 5000),
                    "require_pin": payload.get("require_pin", False),
                    "is_streaming": payload.get("is_streaming", False),
                    "os": payload.get("os", "Windows")
                }
        except socket.timeout:
            continue
        except Exception:
            continue

    sock.close()
    return list(discovered.values())


def check_server_status(ip, port=5000, pin="", viewer_name="موبايل أمي"):
    try:
        url = f"http://{ip}:{port}/api/info"
        resp = requests.get(
            url,
            params={"pin": pin, "client_name": viewer_name},
            timeout=2.5
        )
        if resp.status_code == 403:
            return {"ok": False, "error": "تم حظر هذا الجهاز من لوحة تحكم الحاسبة"}
        if resp.status_code == 200:
            info = resp.json()
            if info.get("require_pin") and not info.get("pin_valid"):
                return {"ok": False, "error": "NEED_PIN", "server_name": info.get("server_name")}
            return {"ok": True, "info": info}
    except Exception:
        pass
    return {"ok": False, "error": "تعذر الوصول إلى الحاسبة. تأكد من تشغيل البرنامج على الحاسبة."}


# ==============================================================================
# 3. تطبيق الموبايل التفاعلي المتوافق مع Flet 0.28+
# ==============================================================================

def main(page: ft.Page):
    page.title = "عارض شاشة الحاسبة الذكي"
    page.rtl = True
    page.padding = 0
    page.spacing = 0
    page.theme_mode = (
        ft.ThemeMode.DARK if storage.data.get("theme_mode") == "dark" else ft.ThemeMode.LIGHT
    )
    page.bgcolor = "#0f172a" if page.theme_mode == ft.ThemeMode.DARK else "#f1f5f9"

    # دعم الأيقونات والتدوير لجميع إصدارات Flet (القديمة والجديدة 0.28+)
    ICONS = getattr(ft, "Icons", getattr(ft, "icons", None))

    def make_rotate(angle):
        if hasattr(ft, "Rotate"):
            return ft.Rotate(angle)
        elif hasattr(ft, "transform") and hasattr(ft.transform, "Rotate"):
            return ft.transform.Rotate(angle)
        return angle

    current_session = {
        "active": False,
        "ip": "",
        "port": 5000,
        "pin": "",
        "server_name": "",
        "rotation_turns": 0,
    }

    def show_message(text, color="#10b981"):
        sb = ft.SnackBar(
            content=ft.Text(text, color="white", weight=ft.FontWeight.BOLD, size=15),
            bgcolor=color,
            duration=2500
        )
        if hasattr(page, "open"):
            page.open(sb)
        else:
            page.snack_bar = sb
            sb.open = True
            page.update()

    def open_dialog_compat(dlg):
        if hasattr(page, "open"):
            page.open(dlg)
        else:
            page.dialog = dlg
            dlg.open = True
            page.update()

    def close_dialog_compat(dlg):
        if hasattr(page, "close"):
            page.close(dlg)
        else:
            dlg.open = False
            page.update()

    # ==========================================================================
    # أ. شاشة المشاهدة الحية (Full-Screen Interactive Stream Viewer)
    # ==========================================================================

    stream_img = ft.Image(
        src="",
        fit=ft.ImageFit.CONTAIN,
        expand=True,
        gapless_playback=True
    )

    rotated_wrapper = ft.Container(
        content=stream_img,
        expand=True,
        alignment=ft.alignment.center,
        rotate=make_rotate(0)
    )

    interactive_viewer = ft.InteractiveViewer(
        min_scale=1.0,
        max_scale=float(storage.data.get("max_zoom_scale", 5.0)),
        content=rotated_wrapper,
        expand=True
    )

    live_server_title = ft.Text("شاشة الحاسبة", size=15, weight=ft.FontWeight.BOLD, color="white")
    live_metrics_txt = ft.Text("FPS: -- | CPU: --% | 🔋 --%", size=12, color="#38bdf8")

    def rotate_screen_view(e):
        current_session["rotation_turns"] = (current_session["rotation_turns"] + 1) % 4
        angle = current_session["rotation_turns"] * 1.57079632679
        rotated_wrapper.rotate = make_rotate(angle)
        page.update()

    def toggle_fit_mode(e):
        if stream_img.fit == ft.ImageFit.CONTAIN:
            stream_img.fit = ft.ImageFit.COVER
            show_message("وضع ملء الشاشة الكامل (Cover)", "#0284c7")
        elif stream_img.fit == ft.ImageFit.COVER:
            stream_img.fit = ft.ImageFit.FILL
            show_message("وضع التمدد الكامل (Fill)", "#0284c7")
        else:
            stream_img.fit = ft.ImageFit.CONTAIN
            show_message("الوضع الطبيعي المتناسق (Contain)", "#0284c7")
        page.update()

    def send_quick_ping_to_pc(message_text):
        if not current_session["active"]:
            return
        try:
            url = f"http://{current_session['ip']}:{current_session['port']}/api/notify"
            requests.post(
                url,
                json={
                    "sender": storage.data.get("viewer_name", "أمي"),
                    "message": message_text
                },
                headers={"X-PIN": str(current_session["pin"])},
                timeout=2.0
            )
            show_message("🔔 تم إظهار التنبيه على شاشة الحاسبة فوراً!", "#10b981")
        except Exception:
            show_message("⚠️ فشل إرسال التنبيه للحاسبة", "#ef4444")

    def open_quick_message_dialog(e):
        custom_msg_field = ft.TextField(
            label="اكتبي رسالة قصيرة تظهر أمامه على الشاشة",
            hint_text="مثال: تعال ساعدني شوية...",
            border_radius=10
        )

        def send_custom(ev):
            txt = custom_msg_field.value.strip()
            if txt:
                close_dialog_compat(dlg)
                send_quick_ping_to_pc(txt)

        def send_preset(preset_txt):
            close_dialog_compat(dlg)
            send_quick_ping_to_pc(preset_txt)

        dlg = ft.AlertDialog(
            title=ft.Text("🔔 إرسال تنبيه فوري لشاشة الحاسبة", weight=ft.FontWeight.BOLD, size=18),
            content=ft.Column(
                tight=True,
                spacing=10,
                controls=[
                    ft.Text("اضغطي على زر جاهز أو اكتبي رسالة:", size=13, color="#94a3b8"),
                    ft.Row(
                        wrap=True,
                        spacing=8,
                        controls=[
                            ft.ElevatedButton("🍲 الغداء جاهز تعال!", on_click=lambda _: send_preset("🍲 الغداء جاهز، تعال تغدى!")),
                            ft.ElevatedButton("👋 تعال أحتاجك شوية", on_click=lambda _: send_preset("👋 تعال يمي أحتاجك شوية!")),
                            ft.ElevatedButton("🔊 نصي صوت الحاسبة", on_click=lambda _: send_preset("🔊 نصي صوت الحاسبة شوية!")),
                            ft.ElevatedButton("❓ شنو جاي تسوي؟", on_click=lambda _: send_preset("❓ حبيبي شنو جاي تسوي بالحاسبة؟")),
                        ]
                    ),
                    ft.Divider(),
                    custom_msg_field
                ]
            ),
            actions=[
                ft.TextButton("إلغاء", on_click=lambda _: close_dialog_compat(dlg)),
                ft.ElevatedButton("إرسال الآن 🚀", bgcolor="#10b981", color="white", on_click=send_custom)
            ]
        )
        open_dialog_compat(dlg)

    def disconnect_stream(e=None):
        current_session["active"] = False
        stream_img.src = ""
        viewer_screen_container.visible = False
        main_navigation_container.visible = True
        refresh_saved_devices_ui()
        page.update()

    viewer_top_bar = ft.Container(
        bgcolor="#1e293b",
        padding=ft.padding.symmetric(horizontal=12, vertical=8),
        content=ft.Row(
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            controls=[
                ft.Row(
                    spacing=8,
                    controls=[
                        ft.Icon(ICONS.CIRCLE, color="#10b981", size=12),
                        ft.Column(
                            spacing=1,
                            controls=[live_server_title, live_metrics_txt]
                        )
                    ]
                ),
                ft.Row(
                    spacing=4,
                    controls=[
                        ft.IconButton(
                            icon=ICONS.NOTIFICATIONS_ACTIVE_ROUNDED,
                            icon_color="#f59e0b",
                            tooltip="إرسال تنبيه للحاسبة",
                            on_click=open_quick_message_dialog
                        ),
                        ft.IconButton(
                            icon=ICONS.SCREEN_ROTATION_ROUNDED,
                            icon_color="#38bdf8",
                            tooltip="تدوير الشاشة 90 درجة",
                            on_click=rotate_screen_view
                        ),
                        ft.IconButton(
                            icon=ICONS.ASPECT_RATIO_ROUNDED,
                            icon_color="#a855f7",
                            tooltip="تغيير أبعاد الشاشة",
                            on_click=toggle_fit_mode
                        ),
                        ft.ElevatedButton(
                            "خروج",
                            icon=ICONS.CLOSE_ROUNDED,
                            bgcolor="#ef4444",
                            color="white",
                            on_click=disconnect_stream
                        )
                    ]
                )
            ]
        )
    )

    viewer_screen_container = ft.Container(
        visible=False,
        expand=True,
        bgcolor="#000000",
        content=ft.Column(
            expand=True,
            spacing=0,
            controls=[
                viewer_top_bar,
                interactive_viewer,
                ft.Container(
                    bgcolor="#0f172a",
                    padding=6,
                    alignment=ft.alignment.center,
                    content=ft.Text(
                        "💡 نصيحة: يمكنكِ تكبير أي جزء من الشاشة بسحب إصبعين (Pinch to Zoom)",
                        size=12,
                        color="#94a3b8"
                    )
                )
            ]
        )
    )

    # ==========================================================================
    # ب. دالة الاتصال بالحاسبة وحفظها تلقائياً
    # ==========================================================================

    def start_connection(ip, port=5000, pin="", custom_name=""):
        ip = ip.strip()
        if not ip or ip == "192.168.1.":
            show_message("⚠️ يرجى اختيار جهاز أو كتابة عنوان الـ IP كاملاً", "#ef4444")
            return

        res = check_server_status(ip, port, pin, storage.data.get("viewer_name", "موبايل أمي"))

        if not res["ok"]:
            if res["error"] == "NEED_PIN":
                ask_pin_dialog(ip, port, res.get("server_name", custom_name))
                return
            else:
                show_message(f"❌ {res['error']}", "#ef4444")
                return

        info = res["info"]
        s_name = custom_name or info.get("server_name", f"حاسبة ({ip})")

        storage.upsert_device(name=s_name, ip=ip, port=port, pin=pin)

        current_session["active"] = True
        current_session["ip"] = ip
        current_session["port"] = port
        current_session["pin"] = pin
        current_session["server_name"] = s_name
        current_session["rotation_turns"] = 0
        rotated_wrapper.rotate = make_rotate(0)

        default_fit = storage.data.get("default_fit", "CONTAIN")
        stream_img.fit = (
            ft.ImageFit.COVER if default_fit == "COVER"
            else (ft.ImageFit.FILL if default_fit == "FILL" else ft.ImageFit.CONTAIN)
        )

        viewer_name_encoded = storage.data.get("viewer_name", "موبايل أمي")
        stream_url = f"http://{ip}:{port}/stream?pin={pin}&client_name={viewer_name_encoded}&t={int(time.time())}"
        stream_img.src = stream_url
        live_server_title.value = f"🖥️ {s_name}"

        main_navigation_container.visible = False
        viewer_screen_container.visible = True
        page.update()

    def ask_pin_dialog(ip, port, s_name):
        pin_field = ft.TextField(
            label="الرمز السري (PIN)",
            password=True,
            can_reveal_password=True,
            keyboard_type=ft.KeyboardType.NUMBER,
            text_align=ft.TextAlign.CENTER,
            text_size=22
        )

        def confirm_pin(e):
            entered_pin = pin_field.value.strip()
            close_dialog_compat(dlg)
            start_connection(ip, port, entered_pin, s_name)

        dlg = ft.AlertDialog(
            title=ft.Text(f"🔒 الحاسبة ({s_name}) محمية برمز"),
            content=pin_field,
            actions=[
                ft.TextButton("إلغاء", on_click=lambda _: close_dialog_compat(dlg)),
                ft.ElevatedButton("اتصال", bgcolor="#10b981", color="white", on_click=confirm_pin)
            ]
        )
        open_dialog_compat(dlg)

    # ==========================================================================
    # ج. التبويب الأول: أجهزتي المحفوظة والربط السريع
    # ==========================================================================

    saved_devices_column = ft.Column(spacing=10)
    discovered_devices_column = ft.Column(spacing=10)
    radar_status_txt = ft.Text("اضغطي على 'بحث بالرادار' للعثور على الحاسبة تلقائياً", size=12, color="#94a3b8")

    def refresh_saved_devices_ui():
        saved_devices_column.controls.clear()
        devices = storage.data.get("saved_devices", [])

        if not devices:
            saved_devices_column.controls.append(
                ft.Container(
                    padding=25,
                    border_radius=15,
                    bgcolor="#1e293b",
                    alignment=ft.alignment.center,
                    content=ft.Column(
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        controls=[
                            ft.Icon(ICONS.DEVICES_OTHER_ROUNDED, size=48, color="#64748b"),
                            ft.Text("لا توجد حاسبات محفوظة بعد", size=16, weight=ft.FontWeight.BOLD, color="#cbd5e1"),
                            ft.Text("بمجرد الاتصال بحاسبتك لأول مرة ستظهر هنا دائماً للاتصال بضغطة واحدة!", size=13, color="#94a3b8", text_align=ft.TextAlign.CENTER)
                        ]
                    )
                )
            )
        else:
            for dev in devices:
                ip = dev["ip"]
                port = dev.get("port", 5000)
                name = dev.get("name", ip)
                pin = dev.get("pin", "")
                is_fav = dev.get("favorite", False)
                last_seen = dev.get("last_connected", "سابقاً")

                card = ft.Container(
                    bgcolor="#1e293b",
                    padding=15,
                    border_radius=16,
                    border=ft.border.all(1.5, "#38bdf8" if is_fav else "#334155"),
                    content=ft.Row(
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        controls=[
                            ft.Row(
                                spacing=12,
                                controls=[
                                    ft.Container(
                                        bgcolor="#0284c7",
                                        padding=12,
                                        border_radius=12,
                                        content=ft.Icon(ICONS.DESKTOP_WINDOWS_ROUNDED, color="white", size=28)
                                    ),
                                    ft.Column(
                                        spacing=3,
                                        controls=[
                                            ft.Row([
                                                ft.Text(name, size=17, weight=ft.FontWeight.BOLD, color="white"),
                                                ft.Icon(ICONS.STAR_ROUNDED, color="#f59e0b", size=18) if is_fav else ft.Container()
                                            ]),
                                            ft.Text(f"IP: {ip}:{port}", size=13, color="#38bdf8"),
                                            ft.Text(f"آخر اتصال: {last_seen}", size=11, color="#94a3b8")
                                        ]
                                    )
                                ]
                            ),
                            ft.Row(
                                spacing=4,
                                controls=[
                                    ft.ElevatedButton(
                                        "مشاهدة ▶",
                                        bgcolor="#10b981",
                                        color="white",
                                        on_click=lambda e, d_ip=ip, d_port=port, d_pin=pin, d_name=name: start_connection(d_ip, d_port, d_pin, d_name)
                                    ),
                                    ft.IconButton(
                                        icon=ICONS.STAR_ROUNDED if is_fav else ICONS.STAR_BORDER_ROUNDED,
                                        icon_color="#f59e0b",
                                        tooltip="تثبيت في المفضلة",
                                        on_click=lambda e, d_ip=ip: (storage.toggle_favorite(d_ip), refresh_saved_devices_ui(), page.update())
                                    ),
                                    ft.IconButton(
                                        icon=ICONS.DELETE_OUTLINE_ROUNDED,
                                        icon_color="#ef4444",
                                        tooltip="حذف من القائمة",
                                        on_click=lambda e, d_ip=ip: (storage.delete_device(d_ip), refresh_saved_devices_ui(), page.update())
                                    )
                                ]
                            )
                        ]
                    )
                )
                saved_devices_column.controls.append(card)

    def run_radar_scan(e=None):
        radar_status_txt.value = "⏳ جاري مسح شبكة الواي فاي للبحث عن الحاسبة..."
        radar_status_txt.color = "#f59e0b"
        discovered_devices_column.controls.clear()
        page.update()

        def bg_scan():
            found_list = discover_lan_servers(timeout=2.0)
            discovered_devices_column.controls.clear()

            if not found_list:
                radar_status_txt.value = "لم يتم العثور على حاسبة تلقائياً. تأكد من تشغيل برنامج الحاسبة أو أدخل الـ IP بالأسفل."
                radar_status_txt.color = "#94a3b8"
            else:
                radar_status_txt.value = f"✅ تم العثور على {len(found_list)} حاسبة متاحة في الشبكة الآن!"
                radar_status_txt.color = "#10b981"

                for item in found_list:
                    d_ip = item["ip"]
                    d_port = item["port"]
                    d_name = item["name"]
                    streaming_now = item["is_streaming"]

                    badge_txt = "🟢 تبث الآن" if streaming_now else "⚪ بالانتظار"
                    badge_col = "#10b981" if streaming_now else "#f59e0b"

                    discovered_devices_column.controls.append(
                        ft.Container(
                            bgcolor="#0f172a",
                            padding=12,
                            border_radius=12,
                            border=ft.border.all(1, "#10b981"),
                            content=ft.Row(
                                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                controls=[
                                    ft.Column(
                                        spacing=2,
                                        controls=[
                                            ft.Text(f"📡 {d_name}", size=16, weight=ft.FontWeight.BOLD, color="white"),
                                            ft.Text(f"{d_ip}:{d_port} | {badge_txt}", size=12, color=badge_col)
                                        ]
                                    ),
                                    ft.ElevatedButton(
                                        "ربط وحفظ 🔗",
                                        bgcolor="#0284c7",
                                        color="white",
                                        on_click=lambda ev, x_ip=d_ip, x_port=d_port, x_name=d_name: start_connection(x_ip, x_port, "", x_name)
                                    )
                                ]
                            )
                        )
                    )
            page.update()

        threading.Thread(target=bg_scan, daemon=True).start()

    manual_name_input = ft.TextField(label="اسم الحاسبة (اختياري)", value="حاسبة مهدي", border_radius=10, bgcolor="#0f172a")
    manual_ip_input = ft.TextField(label="عنوان الـ IP", value="192.168.1.", border_radius=10, bgcolor="#0f172a", rtl=False)
    manual_pin_input = ft.TextField(label="الرمز السري PIN (إن وجد)", border_radius=10, bgcolor="#0f172a", password=True)

    def on_manual_add_connect(e):
        start_connection(
            ip=manual_ip_input.value,
            port=5000,
            pin=manual_pin_input.value.strip(),
            custom_name=manual_name_input.value.strip()
        )

    home_tab_content = ft.Container(
        padding=16,
        expand=True,
        content=ft.Column(
            scroll=ft.ScrollMode.AUTO,
            expand=True,
            spacing=16,
            controls=[
                ft.Container(
                    gradient=ft.LinearGradient(colors=["#0284c7", "#1e3a8a"]),
                    padding=20,
                    border_radius=18,
                    content=ft.Row(
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        controls=[
                            ft.Column(
                                spacing=4,
                                controls=[
                                    ft.Text("أهلاً بكِ في عارض شاشة الحاسبة 🌸", size=20, weight=ft.FontWeight.BOLD, color="white"),
                                    ft.Text("اضغطي على الحاسبة المحفوظة للمشاهدة فوراً بدون كتابة أي كود", size=13, color="#e0f2fe")
                                ]
                            ),
                            ft.Icon(ICONS.CAST_CONNECTED_ROUNDED, color="white", size=42)
                        ]
                    )
                ),
                ft.Row(
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    controls=[
                        ft.Text("⭐ الحاسبات المقترنة المحفوظة", size=18, weight=ft.FontWeight.BOLD, color="#38bdf8"),
                        ft.TextButton("تحديث القائمة", icon=ICONS.REFRESH_ROUNDED, on_click=lambda _: (refresh_saved_devices_ui(), page.update()))
                    ]
                ),
                saved_devices_column,
                ft.Divider(color="#334155"),
                ft.Container(
                    bgcolor="#1e293b",
                    padding=16,
                    border_radius=16,
                    content=ft.Column(
                        spacing=10,
                        controls=[
                            ft.Row(
                                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                controls=[
                                    ft.Text("📡 رادار البحث التلقائي بالشبكة", size=16, weight=ft.FontWeight.BOLD, color="white"),
                                    ft.ElevatedButton(
                                        "بحث بالرادار 🔍",
                                        bgcolor="#0284c7",
                                        color="white",
                                        on_click=run_radar_scan
                                    )
                                ]
                            ),
                            radar_status_txt,
                            discovered_devices_column
                        ]
                    )
                ),
                ft.ExpansionTile(
                    title=ft.Text("➕ إضافة حاسبة جديدة يدوياً (برقم الـ IP)", size=15, weight=ft.FontWeight.BOLD),
                    subtitle=ft.Text("تستخدمين هذا الخيار مرة واحدة فقط وسيتم حفظ الجهاز للأبد", size=12, color="#94a3b8"),
                    collapsed_text_color="white",
                    text_color="#38bdf8",
                    controls=[
                        ft.Container(
                            padding=15,
                            bgcolor="#1e293b",
                            border_radius=12,
                            content=ft.Column(
                                spacing=12,
                                controls=[
                                    manual_name_input,
                                    manual_ip_input,
                                    manual_pin_input,
                                    ft.ElevatedButton(
                                        "ربط وحفظ في أجهزتي المحفوظة 💾",
                                        bgcolor="#10b981",
                                        color="white",
                                        height=46,
                                        width=320,
                                        on_click=on_manual_add_connect
                                    )
                                ]
                            )
                        )
                    ]
                )
            ]
        )
    )

    # ==========================================================================
    # د. التبويب الثاني: إعدادات تطبيق الموبايل الشاملة
    # ==========================================================================

    viewer_name_field = ft.TextField(
        label="الاسم الظاهر في الحاسبة عند اتصالكِ",
        value=storage.data.get("viewer_name", "موبايل أمي"),
        border_radius=10
    )

    auto_connect_switch = ft.Switch(
        label="الاتصال تلقائياً بآخر حاسبة بمجرد فتح التطبيق",
        value=storage.data.get("auto_connect_last", False)
    )

    telemetry_switch = ft.Switch(
        label="عرض سرعة البث وبطارية الحاسبة أعلى الشاشة",
        value=storage.data.get("show_pc_telemetry", True)
    )

    fit_dropdown = ft.Dropdown(
        label="نمط أبعاد الشاشة الافتراضي",
        value=storage.data.get("default_fit", "CONTAIN"),
        options=[
            ft.dropdown.Option("CONTAIN", "متناسق كامل (Contain - ينصح به)"),
            ft.dropdown.Option("COVER", "ملء الشاشة مع قص الأطراف (Cover)"),
            ft.dropdown.Option("FILL", "تمديد كامل للشاشة (Fill)")
        ],
        border_radius=10
    )

    zoom_slider = ft.Slider(
        min=2.0,
        max=8.0,
        divisions=6,
        value=float(storage.data.get("max_zoom_scale", 5.0)),
        label="أقصى تكبير: {value}x"
    )

    def save_mobile_settings(e):
        storage.data["viewer_name"] = viewer_name_field.value.strip() or "موبايل أمي"
        storage.data["auto_connect_last"] = bool(auto_connect_switch.value)
        storage.data["show_pc_telemetry"] = bool(telemetry_switch.value)
        storage.data["default_fit"] = fit_dropdown.value
        storage.data["max_zoom_scale"] = float(zoom_slider.value)
        interactive_viewer.max_scale = float(zoom_slider.value)
        storage.save()
        show_message("✅ تم حفظ إعدادات الموبايل بنجاح!", "#10b981")

    def toggle_app_theme(e):
        if page.theme_mode == ft.ThemeMode.DARK:
            page.theme_mode = ft.ThemeMode.LIGHT
            page.bgcolor = "#f1f5f9"
            storage.data["theme_mode"] = "light"
        else:
            page.theme_mode = ft.ThemeMode.DARK
            page.bgcolor = "#0f172a"
            storage.data["theme_mode"] = "dark"
        storage.save()
        page.update()

    settings_tab_content = ft.Container(
        padding=20,
        expand=True,
        content=ft.Column(
            scroll=ft.ScrollMode.AUTO,
            spacing=18,
            controls=[
                ft.Row(
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    controls=[
                        ft.Text("⚙️ إعدادات وتخصيص التطبيق", size=22, weight=ft.FontWeight.BOLD, color="#38bdf8"),
                        ft.IconButton(
                            icon=ICONS.DARK_MODE_ROUNDED,
                            tooltip="تبديل الوضع الليلي / النهاري",
                            on_click=toggle_app_theme
                        )
                    ]
                ),
                ft.Container(
                    bgcolor="#1e293b",
                    padding=20,
                    border_radius=16,
                    content=ft.Column(
                        spacing=16,
                        controls=[
                            viewer_name_field,
                            auto_connect_switch,
                            telemetry_switch,
                            fit_dropdown,
                            ft.Text("قوة تقريب وتكبير الشاشة بالإصبعين (Max Zoom):", size=14, color="#cbd5e1"),
                            zoom_slider,
                            ft.ElevatedButton(
                                "💾 حفظ الإعدادات",
                                bgcolor="#0284c7",
                                color="white",
                                height=48,
                                width=300,
                                on_click=save_mobile_settings
                            )
                        ]
                    )
                )
            ]
        )
    )

    # ==========================================================================
    # هـ. التنقل السفلي ومراقب الحاسبة بالخلفية
    # ==========================================================================

    body_switcher = ft.Container(expand=True, content=home_tab_content)

    def on_nav_change(e):
        idx = e.control.selected_index
        body_switcher.content = home_tab_content if idx == 0 else settings_tab_content
        page.update()

    nav_bar = ft.NavigationBar(
        selected_index=0,
        bgcolor="#1e293b",
        on_change=on_nav_change,
        destinations=[
            ft.NavigationBarDestination(icon=ICONS.DEVICES_ROUNDED, label="الأجهزة والبث")
            if hasattr(ft, "NavigationBarDestination")
            else ft.NavigationDestination(icon=ICONS.DEVICES_ROUNDED, label="الأجهزة والبث"),
            ft.NavigationBarDestination(icon=ICONS.SETTINGS_ROUNDED, label="الإعدادات")
            if hasattr(ft, "NavigationBarDestination")
            else ft.NavigationDestination(icon=ICONS.SETTINGS_ROUNDED, label="الإعدادات"),
        ]
    )

    main_navigation_container = ft.Column(
        expand=True,
        spacing=0,
        controls=[body_switcher, nav_bar]
    )

    def telemetry_polling_worker():
        while True:
            if current_session["active"] and storage.data.get("show_pc_telemetry", True):
                try:
                    url = f"http://{current_session['ip']}:{current_session['port']}/api/stats"
                    r = requests.get(
                        url,
                        headers={"X-PIN": str(current_session["pin"])},
                        timeout=1.5
                    )
                    if r.status_code == 200:
                        st = r.json()
                        fps_val = st.get("actual_fps", 0)
                        cpu_val = st.get("cpu", 0)
                        bat_val = st.get("battery", 100)
                        p_mode = st.get("privacy_mode", False)

                        if p_mode:
                            live_metrics_txt.value = "🛡️ وضع الخصوصية مفعل من الحاسبة"
                            live_metrics_txt.color = "#f59e0b"
                        else:
                            live_metrics_txt.value = f"⚡ {fps_val} FPS | معالج: {cpu_val:.0f}% | 🔋 {bat_val}%"
                            live_metrics_txt.color = "#38bdf8"
                        page.update()
                except Exception:
                    live_metrics_txt.value = "⚠️ انقطع الاتصال مؤقتاً بالحاسبة..."
                    live_metrics_txt.color = "#ef4444"
                    page.update()
            time.sleep(2.0)

    threading.Thread(target=telemetry_polling_worker, daemon=True).start()

    refresh_saved_devices_ui()
    page.add(main_navigation_container, viewer_screen_container)

    run_radar_scan()

    if storage.data.get("auto_connect_last", False) and storage.data.get("saved_devices"):
        last_dev = storage.data["saved_devices"][0]
        start_connection(
            ip=last_dev["ip"],
            port=last_dev.get("port", 5000),
            pin=last_dev.get("pin", ""),
            custom_name=last_dev.get("name", "")
        )


if __name__ == "__main__":
    ft.app(target=main)