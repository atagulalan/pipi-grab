#!/usr/bin/env python3
"""Native GTK window for pipi grab (evdev → Pi HID)."""
from __future__ import annotations

import math
import threading

import cairo
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import GLib, Gtk  # noqa: E402

from grab_app import WIN_NEEDED, find_devices, grabber, router

# Connecting accent (matches status yellow)
GLOW = (1.0, 176 / 255, 32 / 255)  # #ffb020
IDLE_BORDER = (0x24 / 255, 0x30 / 255, 0x28 / 255)

# Same left inset for titlebar brand and content
PAD = 16

CSS = f"""
* {{ border-radius: 0; }}
window {{
  background: #0c0f0d;
  color: #e7efe8;
  font-family: "IBM Plex Mono", "IBM Plex Mono SemiBold", monospace;
}}
headerbar {{
  background-color: #0c0f0d;
  background-image: none;
  color: #e7efe8;
  border: none;
  border-bottom: 1px solid #243028;
  box-shadow: none;
  padding: 8px {PAD}px;
  min-height: 44px;
  border-radius: 0;
}}
headerbar button {{
  background: transparent;
  border: none;
  box-shadow: none;
  min-height: 28px;
  min-width: 28px;
  padding: 4px;
  color: #e7efe8;
  border-radius: 0;
}}
headerbar button:hover {{
  background: #1a221c;
  border-radius: 0;
}}
.label-brand {{
  font-family: "Syne", sans-serif;
  font-size: 16px;
  font-weight: 800;
  letter-spacing: -0.04em;
  color: #e7efe8;
}}
.label-brand-dot {{
  font-family: "Syne", sans-serif;
  font-size: 16px;
  font-weight: 800;
  letter-spacing: -0.04em;
  color: #c8f542;
}}
.label-st {{
  color: #849288;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}}
.label-st-ok {{ color: #5ddea6; }}
.label-st-bt {{ color: #6aa8ff; }}
.label-st-bad {{ color: #ff6b4a; }}
.label-st-conn {{ color: #ffb020; }}
.dot {{
  min-width: 8px;
  min-height: 8px;
  background: #ff6b4a;
  border-radius: 100%;
  border: none;
  padding: 0;
  margin: 0 2px 0 0;
}}
.dot.on-wifi {{ background: #5ddea6; }}
.dot.on-bt {{ background: #6aa8ff; }}
.dot.on-conn {{ background: #ffb020; }}
button.mode {{
  background: #0c0f0d;
  color: #e7efe8;
  border: none;
  padding: 6px 10px;
  font-family: "IBM Plex Mono", monospace;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  border-radius: 0;
  box-shadow: none;
  min-height: 0;
  min-width: 0;
}}
button.mode:hover {{ background: #121612; }}
button.mode.on-wifi {{
  background: #c8f542;
  color: #10140f;
}}
button.mode.on-bt {{
  background: #6aa8ff;
  color: #061018;
}}
.grab-pad {{
  background: #070907;
  border: 1px dashed #243028;
  padding: 20px;
  min-height: 220px;
  border-radius: 0;
}}
.grab-pad:hover {{ border-color: #3a4a3e; }}
.grab-pad.on {{
  border: 1px solid #ffb020;
  box-shadow: 0 0 0 3px rgba(255, 176, 32, 0.14);
}}
.grab-big {{
  font-family: "Syne", sans-serif;
  font-size: 22px;
  font-weight: 800;
  letter-spacing: -0.04em;
  color: #e7efe8;
}}
.grab-big.on {{ color: #ffb020; }}
.grab-sub {{
  color: #849288;
  font-size: 11px;
  line-height: 1.45;
}}
.kbd {{
  font-family: "IBM Plex Mono", monospace;
  font-size: 10px;
  color: #e7efe8;
  border: 1px solid #243028;
  padding: 1px 5px;
  border-radius: 0;
  background: transparent;
}}
button.winbtn {{
  background: transparent;
  color: #849288;
  border: 1px solid #243028;
  padding: 0;
  min-width: 28px;
  min-height: 28px;
  font-family: "IBM Plex Mono", monospace;
  font-size: 14px;
  font-weight: 600;
  letter-spacing: 0;
  border-radius: 0;
  box-shadow: none;
}}
button.winbtn:hover {{
  color: #e7efe8;
  border-color: #3a4a3e;
  background: #121612;
}}
button.winbtn.close:hover {{
  color: #10140f;
  background: #ff6b4a;
  border-color: #ff6b4a;
}}
""".encode()


class GlowBorder(Gtk.Overlay):
    """Conic spinning border (CSS animated-border-box style), radius 0."""

    BORDER = 1
    GLOW_PAD = 1  # soft bloom outside the chip
    PERIOD = 2.5  # seconds per turn

    def __init__(self, child: Gtk.Widget) -> None:
        super().__init__()
        self._angle = 0.0
        self._spinning = False
        self._show_idle = True
        self.set_hexpand(False)
        self.set_vexpand(False)
        self.set_halign(Gtk.Align.START)
        self.set_valign(Gtk.Align.CENTER)

        self.da = Gtk.DrawingArea()
        self.da.set_hexpand(False)
        self.da.set_vexpand(False)
        self.da.set_draw_func(self._draw)
        self.set_child(self.da)

        hold = Gtk.Box()
        hold.set_halign(Gtk.Align.FILL)
        hold.set_valign(Gtk.Align.FILL)
        g = self.GLOW_PAD
        b = self.BORDER
        hold.set_margin_top(g + b)
        hold.set_margin_bottom(g + b)
        hold.set_margin_start(g + b)
        hold.set_margin_end(g + b)
        child.set_hexpand(False)
        child.set_vexpand(False)
        hold.append(child)
        self.add_overlay(hold)
        # Size from the chip, not the DrawingArea (which wants 0×∞ otherwise)
        self.set_measure_overlay(hold, True)

    def set_spinning(self, on: bool) -> None:
        self._spinning = on
        self._show_idle = not on
        self.da.queue_draw()

    def set_idle_border(self, on: bool) -> None:
        self._show_idle = on and not self._spinning
        self.da.queue_draw()

    def tick(self, dt: float) -> None:
        if not self._spinning:
            return
        self._angle = (self._angle + (2 * math.pi / self.PERIOD) * dt) % (2 * math.pi)
        self.da.queue_draw()

    def _ring_clip(self, cr: cairo.Context, x0: float, y0: float, x1: float, y1: float, b: float) -> None:
        cr.rectangle(x0, y0, x1 - x0, y1 - y0)
        cr.rectangle(x0 + b, y0 + b, (x1 - x0) - 2 * b, (y1 - y0) - 2 * b)
        cr.set_fill_rule(cairo.FillRule.EVEN_ODD)
        cr.clip()

    def _draw(self, _area: Gtk.DrawingArea, cr: cairo.Context, w: int, h: int) -> None:
        if w <= 0 or h <= 0:
            return
        g = self.GLOW_PAD
        b = float(self.BORDER)
        x0, y0 = float(g), float(g)
        x1, y1 = float(w - g), float(h - g)
        if x1 - x0 < 2 * b + 2 or y1 - y0 < 2 * b + 2:
            return

        if self._spinning:
            cx, cy = (x0 + x1) * 0.5, (y0 + y1) * 0.5
            rad = math.hypot(w, h)

            # Keep a visible base ring so the chip doesn't "lose" its border
            cr.save()
            self._ring_clip(cr, x0, y0, x1, y1, b)
            cr.set_source_rgba(GLOW[0], GLOW[1], GLOW[2], 0.22)
            cr.paint()
            cr.restore()

            # Soft bloom outside (tight, all four sides)
            cr.save()
            self._ring_clip(cr, x0 - 1, y0 - 1, x1 + 1, y1 + 1, b + 1)
            self._paint_conic(cr, cx, cy, rad, sweep=0.30, alpha_scale=0.28)
            cr.restore()

            # Bright rotating sweep on the border
            cr.save()
            self._ring_clip(cr, x0, y0, x1, y1, b)
            self._paint_conic(cr, cx, cy, rad, sweep=0.35, alpha_scale=1.0)
            cr.restore()
            return

        if self._show_idle:
            cr.set_source_rgb(*IDLE_BORDER)
            cr.set_line_width(1)
            cr.rectangle(x0 + 0.5, y0 + 0.5, (x1 - x0) - 1, (y1 - y0) - 1)
            cr.stroke()

    def _paint_conic(
        self,
        cr: cairo.Context,
        cx: float,
        cy: float,
        radius: float,
        *,
        sweep: float,
        alpha_scale: float,
    ) -> None:
        # conic-gradient(transparent, color, transparent sweep)
        steps = 128
        half = sweep * 0.5
        for i in range(steps):
            t = i / steps  # 0..1 around circle
            # distance from head (0) within sweep window
            if t <= sweep:
                # peak in the middle of the sweep
                alpha = 1.0 - abs(t - half) / half if half > 0 else 1.0
            else:
                alpha = 0.0
            alpha = max(0.0, min(1.0, alpha)) * alpha_scale
            if alpha <= 0.02:
                continue
            a0 = self._angle + (i / steps) * 2 * math.pi
            a1 = self._angle + ((i + 1) / steps) * 2 * math.pi
            cr.set_source_rgba(GLOW[0], GLOW[1], GLOW[2], alpha)
            cr.move_to(cx, cy)
            cr.line_to(cx + math.cos(a0) * radius, cy + math.sin(a0) * radius)
            cr.line_to(cx + math.cos(a1) * radius, cy + math.sin(a1) * radius)
            cr.close_path()
            cr.fill()


class GrabWindow(Gtk.ApplicationWindow):
    def __init__(self, app: Gtk.Application) -> None:
        super().__init__(application=app, title="pipi.grab")
        self.set_default_size(420, 380)
        self.set_resizable(False)

        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_display(
            self.get_display(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        brand = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        brand.set_valign(Gtk.Align.CENTER)
        for text, cls in (("pipi", "label-brand"), (".", "label-brand-dot"), ("grab", "label-brand")):
            lab = Gtk.Label(label=text)
            lab.add_css_class(cls)
            brand.append(lab)

        st_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        st_box.set_valign(Gtk.Align.CENTER)
        self.dot = Gtk.Box()
        self.dot.add_css_class("dot")
        self.dot.set_valign(Gtk.Align.CENTER)
        self.status = Gtk.Label(label="connecting")
        self.status.add_css_class("label-st")
        st_box.append(self.dot)
        st_box.append(self.status)

        win_btns = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        win_btns.set_valign(Gtk.Align.CENTER)
        btn_min = Gtk.Button(label="–")
        btn_min.add_css_class("winbtn")
        btn_min.set_cursor_from_name("pointer")
        btn_min.set_tooltip_text("Minimize")
        btn_min.connect("clicked", lambda *_: self.minimize())
        btn_close = Gtk.Button(label="×")
        btn_close.add_css_class("winbtn")
        btn_close.add_css_class("close")
        btn_close.set_cursor_from_name("pointer")
        btn_close.set_tooltip_text("Close")
        btn_close.connect("clicked", lambda *_: self.close())
        win_btns.append(btn_min)
        win_btns.append(btn_close)

        right = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        right.set_valign(Gtk.Align.CENTER)
        right.append(st_box)
        right.append(win_btns)

        header = Gtk.HeaderBar()
        header.set_show_title_buttons(False)  # no native − □ ×
        header.set_title_widget(Gtk.Label())
        header.pack_start(brand)
        header.pack_end(right)
        self.set_titlebar(header)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        root.set_margin_top(16)
        root.set_margin_bottom(PAD)
        root.set_margin_start(PAD)
        root.set_margin_end(PAD)
        self.set_child(root)

        modes = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        # Pull row left so chip faces still share grab-pad edge while left glow is visible
        modes.set_margin_start(-(GlowBorder.GLOW_PAD + GlowBorder.BORDER))
        self.btn_wifi = Gtk.Button(label="WiFi")
        self.btn_bt = Gtk.Button(label="Bluetooth")
        for b in (self.btn_wifi, self.btn_bt):
            b.add_css_class("mode")
            b.set_cursor_from_name("pointer")
        self.btn_wifi.connect("clicked", lambda *_: self._set_mode("wifi"))
        self.btn_bt.connect("clicked", lambda *_: self._set_mode("bt"))
        self.glow_wifi = GlowBorder(self.btn_wifi)
        self.glow_bt = GlowBorder(self.btn_bt)
        modes.append(self.glow_wifi)
        modes.append(self.glow_bt)
        root.append(modes)

        self.grab_pad = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.grab_pad.add_css_class("grab-pad")
        self.grab_pad.set_valign(Gtk.Align.FILL)
        self.grab_pad.set_halign(Gtk.Align.FILL)
        self.grab_pad.set_hexpand(True)
        self.grab_pad.set_vexpand(True)
        self.grab_pad.set_cursor_from_name("pointer")

        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        inner.set_valign(Gtk.Align.CENTER)
        inner.set_halign(Gtk.Align.CENTER)
        inner.set_vexpand(True)
        inner.set_hexpand(True)

        self.grab_title = Gtk.Label(label="GRAB")
        self.grab_title.add_css_class("grab-big")
        self.grab_title.set_halign(Gtk.Align.CENTER)

        # Same line: idle device hint ↔ release chord (slide up + crossfade)
        idle_line = Gtk.Label(label="Keyboard & Mouse → Device")
        idle_line.add_css_class("grab-sub")
        idle_line.set_halign(Gtk.Align.CENTER)

        release_line = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        release_line.set_halign(Gtk.Align.CENTER)
        release_line.set_valign(Gtk.Align.CENTER)
        r1 = Gtk.Label(label="To Release,")
        r1.add_css_class("grab-sub")
        kbd = Gtk.Label(label="Win")
        kbd.add_css_class("kbd")
        r2 = Gtk.Label(label=f"× {WIN_NEEDED}")
        r2.add_css_class("grab-sub")
        release_line.append(r1)
        release_line.append(kbd)
        release_line.append(r2)

        self.sub_stack = Gtk.Stack()
        self.sub_stack.set_transition_type(Gtk.StackTransitionType.SLIDE_UP)
        self.sub_stack.set_transition_duration(280)
        self.sub_stack.set_hhomogeneous(True)
        self.sub_stack.set_vhomogeneous(True)
        self.sub_stack.add_named(idle_line, "idle")
        self.sub_stack.add_named(release_line, "release")
        self.sub_stack.set_visible_child_name("idle")

        inner.append(self.grab_title)
        inner.append(self.sub_stack)
        self.grab_pad.append(inner)

        click = Gtk.GestureClick()
        click.connect("released", lambda *_: self._toggle_grab())
        self.grab_pad.add_controller(click)
        root.append(self.grab_pad)

        self._busy = False
        self._connecting = not router.ok
        self._connect_target = router.mode if self._connecting else None
        self._paint()
        GLib.timeout_add(500, self._tick)
        GLib.timeout_add(16, self._spin_tick)  # ~60fps conic

    def _clear_status_classes(self) -> None:
        for c in ("label-st-ok", "label-st-bt", "label-st-bad", "label-st-conn"):
            self.status.remove_css_class(c)
        for c in ("on-wifi", "on-bt", "on-conn"):
            self.dot.remove_css_class(c)

    def _spin_tick(self) -> bool:
        dt = 16 / 1000.0
        connecting = self._connecting or self._busy
        self.glow_wifi.set_spinning(connecting and self._connect_target == "wifi")
        self.glow_bt.set_spinning(connecting and self._connect_target == "bt")
        self.glow_wifi.tick(dt)
        self.glow_bt.tick(dt)
        return True

    def _paint(self) -> None:
        mode = router.mode
        grabbed = grabber.active
        connecting = self._connecting or self._busy
        self.btn_wifi.remove_css_class("on-wifi")
        self.btn_bt.remove_css_class("on-bt")
        # Don't light mode chips until transport is actually ready
        if not connecting and router.ok:
            if mode == "wifi":
                self.btn_wifi.add_css_class("on-wifi")
                self.glow_wifi.set_idle_border(False)
                self.glow_bt.set_idle_border(True)
            else:
                self.btn_bt.add_css_class("on-bt")
                self.glow_bt.set_idle_border(False)
                self.glow_wifi.set_idle_border(True)
        elif not connecting:
            self.glow_wifi.set_idle_border(True)
            self.glow_bt.set_idle_border(True)

        self.grab_pad.remove_css_class("on")
        self.grab_title.remove_css_class("on")
        if grabbed:
            self.grab_pad.add_css_class("on")
            self.grab_title.add_css_class("on")
            self.grab_title.set_text("GRABBED")
            if self.sub_stack.get_visible_child_name() != "release":
                self.sub_stack.set_transition_type(Gtk.StackTransitionType.SLIDE_UP)
                self.sub_stack.set_visible_child_name("release")
        else:
            self.grab_title.set_text("GRAB")
            if self.sub_stack.get_visible_child_name() != "idle":
                self.sub_stack.set_transition_type(Gtk.StackTransitionType.SLIDE_DOWN)
                self.sub_stack.set_visible_child_name("idle")

        self._clear_status_classes()
        # Yellow while handshake in progress (_busy / _connecting), not when merely "mode" flipped
        if self._connecting or self._busy:
            self.status.add_css_class("label-st-conn")
            self.dot.add_css_class("on-conn")
            self.status.set_text("connecting")
        elif router.ok:
            if mode == "bt":
                self.status.add_css_class("label-st-bt")
                self.dot.add_css_class("on-bt")
                tag = "bluetooth"
            else:
                self.status.add_css_class("label-st-ok")
                self.dot.add_css_class("on-wifi")
                tag = "wifi"
            if grabbed:
                tag += " · grab"
            self.status.set_text(tag)
        else:
            self.status.add_css_class("label-st-bad")
            self.status.set_text("down")

    def _tick(self) -> bool:
        # ok is only True after agent handshake — safe to leave connecting
        if self._connecting and not self._busy and router.ok:
            self._connecting = False
            self._connect_target = None
        elif self._connecting and not self._busy and not router.ok and router.last_error:
            self._connecting = False
            self._connect_target = None
        self._paint()
        return True

    def _set_mode(self, mode: str) -> None:
        if self._busy:
            return
        if grabber.active:
            return

        def work() -> None:
            try:
                router.set_mode(mode)
            except Exception:
                pass
            finally:
                self._connecting = False
                self._busy = False
                self._connect_target = None
                GLib.idle_add(self._paint)

        self._busy = True
        self._connecting = True
        self._connect_target = "bt" if mode in ("bt", "bluetooth") else "wifi"
        self._paint()
        threading.Thread(target=work, daemon=True).start()

    def _toggle_grab(self) -> None:
        if self._busy:
            return

        def work() -> None:
            try:
                if grabber.active:
                    grabber.ungrab()
                else:
                    grabber.grab()
            except Exception:
                pass
            finally:
                self._busy = False
                GLib.idle_add(self._paint)

        self._busy = True
        threading.Thread(target=work, daemon=True).start()


class GrabApp(Gtk.Application):
    def __init__(self) -> None:
        super().__init__(application_id="local.pipi.grab")
        self._win: GrabWindow | None = None

    def do_startup(self) -> None:  # noqa: N802
        Gtk.Application.do_startup(self)
        settings = Gtk.Settings.get_default()
        if settings is not None:
            settings.set_property("gtk-application-prefer-dark-theme", True)

    def do_activate(self) -> None:  # noqa: N802
        if self._win is None:
            self._win = GrabWindow(self)
        self._win.present()


def main() -> None:
    print(f"devices: {[d.name for d in find_devices()]}", flush=True)
    # Show window first; connect in background so status can be yellow "connecting"
    print("opening GTK window …", flush=True)

    def connect_bg() -> None:
        try:
            print(f"starting {router.mode} → pipi ...", flush=True)
            router.start()
        except Exception as e:
            router.last_error = str(e)
            print(f"warn: {e}", flush=True)
            if router.mode == "bt":
                try:
                    router.set_mode("wifi")
                except Exception as e2:
                    print(f"wifi also failed: {e2}", flush=True)

    threading.Thread(target=connect_bg, daemon=True).start()
    app = GrabApp()
    app.run(None)


if __name__ == "__main__":
    main()
