from __future__ import annotations

from typing import cast

from qtpy import QtCore, QtWidgets

from .crawl_options import AuditProfile, CrawlOptions, parse_header_lines
from .theme import current_theme

_PROFILE_CHOICES = (
    (AuditProfile.LIGHTWEIGHT, "Lightweight — local parse only, no per-page probes"),
    (AuditProfile.STANDARD, "Standard — bounded link/canonical/redirect probing"),
    (AuditProfile.DEEP, "Deep — full probing, rendering, integrations"),
)

# v3 G3 Stage 2 — engine id -> field label for the "AI share of voice" group.
_SOV_ENGINES: tuple[tuple[str, str], ...] = (
    ("openai", "ChatGPT (OpenAI) key"),
    ("perplexity", "Perplexity key"),
    ("gemini", "Gemini key"),
)


def _playwright_available() -> bool:
    """Return True when the optional silentfrog[geo-render] extra is importable."""
    try:
        from playwright import sync_api  # type: ignore[import]  # noqa: F401
    except Exception:
        return False
    return True


def _embeddings_available() -> bool:
    """Return True when the optional silentfrog[embeddings] extra is importable."""
    try:
        import sentence_transformers  # type: ignore[import]  # noqa: F401
    except Exception:
        return False
    return True


async def _summarize_sov_test(keys: dict[str, str]) -> str:
    """Test each keyed AI-engine and join 'engine: message' results with
    ' · ' — 'no key' for empty fields, never awaiting a network call for
    those. Runs inside the single ``asyncio.run()`` call ``_on_sov_test``
    starts on its worker thread."""
    from .integrations.ai_engines import test_connection

    parts: list[str] = []
    for engine, key in keys.items():
        if not key:
            parts.append(f"{engine}: no key")
            continue
        _ok, message = await test_connection(engine, key)
        parts.append(f"{engine}: {message}")
    return " · ".join(parts)


class CrawlSettingsDialog(QtWidgets.QDialog):
    """Lightweight dialog that groups gentle crawl controls away from the main window."""

    def __init__(
        self, options: CrawlOptions, parent: QtWidgets.QWidget | None = None, *, show_profile: bool = False
    ) -> None:
        super().__init__(parent)
        # The audit-profile selector is shown for site crawls only; single-page
        # audits stay DEEP (H4), so their dialog hides it and preserves the profile.
        self._show_profile = show_profile
        theme = self._configure_dialog()
        outer = QtWidgets.QVBoxLayout(self)
        # B1: the four setting groups scroll inside a viewport so a tall dialog
        # never pushes the button row off-screen. OK/Cancel/Help stay pinned
        # below the scroll area and reachable above the taskbar.
        body = QtWidgets.QWidget()
        body_layout = QtWidgets.QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.addWidget(self._build_general_group())
        body_layout.addWidget(self._build_geo_group())
        body_layout.addWidget(self._build_semrush_group(theme))
        body_layout.addWidget(self._build_ai_engines_group(theme))
        body_layout.addWidget(self._build_advanced_group(theme))
        body_layout.addStretch(1)
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)
        outer.addWidget(self._build_button_box())
        self._connect_signals()
        self._applying_preset = False
        self._initialize_options(options)

    def _build_geo_group(self) -> QtWidgets.QGroupBox:
        geo_box = QtWidgets.QGroupBox("GEO checks")
        geo_layout = QtWidgets.QFormLayout(geo_box)
        self.chk_ssr_parity = QtWidgets.QCheckBox("Run SSR parity check (requires Playwright)")
        self.chk_ssr_parity.setToolTip(
            "Optional. Compares the server-rendered DOM with the post-JS DOM via headless Chromium. "
            "Install with: pip install silentfrog[geo-render] && playwright install chromium. "
            "When disabled or when Playwright is missing, the AI Visibility row reports 'not measured' "
            "and the GEO Score is not affected."
        )
        if not _playwright_available():
            self.chk_ssr_parity.setEnabled(False)
            self.chk_ssr_parity.setToolTip(
                self.chk_ssr_parity.toolTip() + "\n\nPlaywright is not installed: enable by running "
                "`pip install silentfrog[geo-render]` and `playwright install chromium`."
            )
        geo_layout.addRow(self.chk_ssr_parity)
        self.chk_bot_render = QtWidgets.QCheckBox("Per-bot SSR rendering (render as each AI bot)")
        self.chk_bot_render.setToolTip(
            "Optional. Renders the page once per audited AI/search bot user-agent (19 bots) and "
            "compares the rendered DOMs — surfaces WAF blocks, cloaking, and UA-dependent content in "
            "the Bot Matrix SSR column. Slow (one render per bot per page); off by default. Requires "
            "Playwright and a Deep audit profile."
        )
        if not _playwright_available():
            self.chk_bot_render.setEnabled(False)
            self.chk_bot_render.setToolTip(
                self.chk_bot_render.toolTip() + "\n\nPlaywright is not installed: enable by running "
                "`pip install silentfrog[geo-render]` and `playwright install chromium`."
            )
        geo_layout.addRow(self.chk_bot_render)
        self.chk_render_js = QtWidgets.QCheckBox("Crawl JavaScript-rendered links (SPA sites)")
        self.chk_render_js.setToolTip(
            "Optional. Renders each page with headless Chromium and follows links found in the "
            "JS-rendered DOM as well as the raw HTML — needed to crawl React/Vue/Angular route "
            "graphs that inject their navigation. Slow (one render per page); off by default. "
            "Requires Playwright and a Deep audit profile."
        )
        if not _playwright_available():
            self.chk_render_js.setEnabled(False)
            self.chk_render_js.setToolTip(
                self.chk_render_js.toolTip() + "\n\nPlaywright is not installed: enable by running "
                "`pip install silentfrog[geo-render]` and `playwright install chromium`."
            )
        geo_layout.addRow(self.chk_render_js)
        self.chk_tech_stack = QtWidgets.QCheckBox("Detect tech stack (Wappalyzer-style)")
        self.chk_tech_stack.setToolTip(
            "Optional. Identifies the CMS, frameworks, analytics, CDN and server from the page's "
            "HTML, headers and scripts. Off by default; adds a 'tech_stack' block to the audit."
        )
        geo_layout.addRow(self.chk_tech_stack)
        self.chk_topic_embeddings = QtWidgets.QCheckBox("Topic embeddings (local model)")
        self.chk_topic_embeddings.setToolTip(
            "Optional. Scores how well the body paragraphs stay on the topic the title promises, "
            "using a local sentence-transformers model (all-MiniLM-L6-v2). Fully local — no text "
            "leaves the machine; the first run downloads the model (~90 MB). Off by default."
        )
        if not _embeddings_available():
            self.chk_topic_embeddings.setEnabled(False)
            self.chk_topic_embeddings.setToolTip(
                self.chk_topic_embeddings.toolTip() + "\n\nsentence-transformers is not installed: enable "
                "by running `pip install silentfrog[embeddings]`."
            )
        geo_layout.addRow(self.chk_topic_embeddings)
        return geo_box

    def _build_semrush_group(self, theme: str) -> QtWidgets.QGroupBox:
        """Authority (Semrush) controls. Optional + off/empty by default —
        the key is persisted to the OS keychain, the daily cap to QSettings."""
        box = QtWidgets.QGroupBox("Authority (Semrush)")
        form = QtWidgets.QFormLayout(box)
        self.edit_semrush_key = QtWidgets.QLineEdit()
        self.edit_semrush_key.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
        self.edit_semrush_key.setPlaceholderText("Semrush API key (stored in the OS keychain)")
        self.edit_semrush_key.setStyleSheet(self._field_stylesheet(theme))
        self.edit_semrush_key.setToolTip(
            "Optional. Fetches domain Authority Score, organic footprint, and backlink signals from the "
            "Semrush Analytics API. Off/empty by default; per §1.5 these off-page signals never penalise "
            "the GEO Score. Calls are metered — see the daily cap below."
        )
        form.addRow("API key", self.edit_semrush_key)
        self.spin_semrush_max_calls = QtWidgets.QSpinBox()
        self.spin_semrush_max_calls.setRange(1, 10000)
        self.spin_semrush_max_calls.setValue(100)
        form.addRow("Max Semrush calls per day", self.spin_semrush_max_calls)
        self.btn_semrush_test = QtWidgets.QPushButton("Test connection")
        self.btn_semrush_test.clicked.connect(self._on_semrush_test)
        self.lbl_semrush_test = QtWidgets.QLabel("")
        test_widget = QtWidgets.QWidget()
        test_row = QtWidgets.QHBoxLayout(test_widget)
        test_row.setContentsMargins(0, 0, 0, 0)
        test_row.addWidget(self.btn_semrush_test)
        test_row.addWidget(self.lbl_semrush_test)
        test_row.addStretch(1)
        form.addRow(test_widget)
        return box

    def _build_ai_engines_group(self, theme: str) -> QtWidgets.QGroupBox:
        """BYO-key AI share-of-voice controls (v3 G3). Optional + empty by
        default — each key is persisted to the OS keychain only, never to
        QSettings or disk; sampling itself stays gated on
        SILENTFROG_AI_SOV_ENABLE regardless of whether a key is set."""
        box = QtWidgets.QGroupBox("AI share of voice (BYO keys)")
        form = QtWidgets.QFormLayout(box)
        intro = QtWidgets.QLabel(
            "Samples ChatGPT, Perplexity and Gemini with your own API keys. Off by default — enable "
            "with SILENTFROG_AI_SOV_ENABLE=1. Keys are stored in the OS keychain, never in the repo."
        )
        intro.setWordWrap(True)
        form.addRow(intro)
        self.edit_sov_keys: dict[str, QtWidgets.QLineEdit] = {}
        for engine, label in _SOV_ENGINES:
            edit = QtWidgets.QLineEdit()
            edit.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
            edit.setPlaceholderText(f"{label} (stored in the OS keychain)")
            edit.setStyleSheet(self._field_stylesheet(theme))
            form.addRow(label, edit)
            self.edit_sov_keys[engine] = edit
        self.btn_sov_test = QtWidgets.QPushButton("Test keys")
        self.btn_sov_test.clicked.connect(self._on_sov_test)
        self.lbl_sov_test = QtWidgets.QLabel("")
        self.lbl_sov_test.setWordWrap(True)
        test_widget = QtWidgets.QWidget()
        test_row = QtWidgets.QHBoxLayout(test_widget)
        test_row.setContentsMargins(0, 0, 0, 0)
        test_row.addWidget(self.btn_sov_test)
        test_row.addWidget(self.lbl_sov_test)
        test_row.addStretch(1)
        form.addRow(test_widget)
        return box

    def _configure_dialog(self) -> str:
        self.setWindowTitle("Crawl settings")
        # Min height kept low so the dialog can shrink to fit short screens; the
        # scroll area supplies the overflow. Actual size is screen-capped below.
        self.setMinimumSize(440, 360)
        # Toggle only the context-help "?" off. A single-flag toggle avoids the
        # platform quirk where rebuilding the whole flag mask drops the native
        # close button; keep the close button explicit so the title-bar X (and
        # Cancel/Esc) always dismiss the dialog.
        self.setWindowFlag(QtCore.Qt.WindowType.WindowCloseButtonHint, True)
        self.setWindowFlag(QtCore.Qt.WindowType.WindowContextHelpButtonHint, False)
        style = QtWidgets.QStyleFactory.create("Fusion")
        if style:
            self.setStyle(style)
        app = cast(QtWidgets.QApplication | None, QtWidgets.QApplication.instance())
        return current_theme(app)

    def _build_general_group(self) -> QtWidgets.QGroupBox:
        general_box = QtWidgets.QGroupBox("General behaviour")
        general_layout = QtWidgets.QFormLayout(general_box)
        self.chk_gentle = QtWidgets.QCheckBox("Enable gentle crawl mode")
        self.chk_gentle.setStyleSheet(self._checkbox_stylesheet(current_theme(QtWidgets.QApplication.instance())))
        general_layout.addRow(self.chk_gentle)

        self.spin_parallel = QtWidgets.QSpinBox()
        self.spin_parallel.setRange(1, 8)
        general_layout.addRow("Max parallel requests", self.spin_parallel)

        self.profile_combo = QtWidgets.QComboBox()
        for profile, label in _PROFILE_CHOICES:
            self.profile_combo.addItem(label, profile.value)
        self.profile_combo.setToolTip(
            "Audit profile gates extra HTTP requests, rendering, and integrations. Local SEO / structure / "
            "E-E-A-T / schema parsing and site-wide discovery run in every profile. Single-page audits always "
            "run Deep."
        )
        if self._show_profile:
            general_layout.addRow("Audit profile", self.profile_combo)

        presets_widget = self._build_presets_widget()
        general_layout.addRow("Presets", presets_widget)
        return general_box

    def _build_presets_widget(self) -> QtWidgets.QWidget:
        presets_widget = QtWidgets.QWidget()
        presets_layout = QtWidgets.QHBoxLayout(presets_widget)
        presets_layout.setContentsMargins(0, 0, 0, 0)
        self.preset_group = QtWidgets.QButtonGroup(self)
        self.btn_preset_standard = QtWidgets.QRadioButton("Standard")
        self.btn_preset_gentle = QtWidgets.QRadioButton("Gentle")
        self.btn_preset_custom = QtWidgets.QRadioButton("Custom")
        for btn in (self.btn_preset_standard, self.btn_preset_gentle, self.btn_preset_custom):
            self.preset_group.addButton(btn)
            presets_layout.addWidget(btn)
        return presets_widget

    def _build_advanced_group(self, theme: str) -> QtWidgets.QGroupBox:
        self.adv_group = QtWidgets.QGroupBox("Advanced headers")
        adv_layout = QtWidgets.QVBoxLayout(self.adv_group)
        self.headers_label = QtWidgets.QLabel("Custom headers (Key: Value per line)")
        adv_layout.addWidget(self.headers_label)
        headers_help = QtWidgets.QLabel(
            "Each line becomes an HTTP header (e.g. Authorization: Bearer token123). "
            "Set them only when the site expects additional headers."
        )
        headers_help.setWordWrap(True)
        headers_help.setStyleSheet(f"color:{'#9fa3ab' if theme == 'dark' else '#666'};")
        adv_layout.addWidget(headers_help)

        self.txt_headers = QtWidgets.QPlainTextEdit()
        self.txt_headers.setPlaceholderText("Authorization: Bearer …")
        self.txt_headers.setFixedHeight(80)
        self.txt_headers.setStyleSheet(self._field_stylesheet(theme))
        adv_layout.addWidget(self.txt_headers)

        adv_layout.addWidget(QtWidgets.QLabel("Cookies"))
        cookies_help = QtWidgets.QLabel(
            "Raw Cookie header, such as session=abc; theme=dark, if the crawl must mimic an authenticated visit."
        )
        cookies_help.setWordWrap(True)
        cookies_help.setStyleSheet(f"color:{'#9fa3ab' if theme == 'dark' else '#666'};")
        adv_layout.addWidget(cookies_help)
        self.edit_cookies = QtWidgets.QLineEdit()
        self.edit_cookies.setPlaceholderText("session=abc; theme=dark")
        self.edit_cookies.setStyleSheet(self._field_stylesheet(theme))
        adv_layout.addWidget(self.edit_cookies)

        adv_layout.addWidget(QtWidgets.QLabel("Custom extraction rules"))
        extraction_help = QtWidgets.QLabel(
            "One rule per line: <b>Name | type | selector | attribute | post_regex</b>. "
            "type is css / xpath / regex / attribute (default css). Example: "
            "<code>Price | css | span.price</code> or <code>SKU | attribute | meta[name=sku] | content</code>."
        )
        extraction_help.setWordWrap(True)
        extraction_help.setStyleSheet(f"color:{'#9fa3ab' if theme == 'dark' else '#666'};")
        adv_layout.addWidget(extraction_help)
        self.txt_custom_extraction = QtWidgets.QPlainTextEdit()
        self.txt_custom_extraction.setPlaceholderText("Price | css | span.price")
        self.txt_custom_extraction.setFixedHeight(90)
        self.txt_custom_extraction.setStyleSheet(self._field_stylesheet(theme))
        adv_layout.addWidget(self.txt_custom_extraction)

        self.chk_allow_insecure_tls = QtWidgets.QCheckBox("Allow insecure TLS (skip certificate verification)")
        self.chk_allow_insecure_tls.setStyleSheet(self._checkbox_stylesheet(theme))
        self.chk_allow_insecure_tls.setToolTip(
            "Off by default. Skips TLS certificate verification for this crawl's fetches so you can audit "
            "trusted self-signed or intranet hosts. This exposes the crawl to man-in-the-middle tampering — "
            "enable only for hosts you control and trust."
        )
        adv_layout.addWidget(self.chk_allow_insecure_tls)

        self.chk_allow_private_network = QtWidgets.QCheckBox("Allow private-network targets (disable SSRF protection)")
        self.chk_allow_private_network.setStyleSheet(self._checkbox_stylesheet(theme))
        self.chk_allow_private_network.setToolTip(
            "Off by default. Lets this crawl reach loopback / intranet / link-local hosts that the SSRF guard "
            "normally blocks, so you can audit internal sites. A crawled page can then steer fetches at your "
            "internal network — enable only for hosts you control and trust."
        )
        adv_layout.addWidget(self.chk_allow_private_network)
        return self.adv_group

    def _build_button_box(self) -> QtWidgets.QDialogButtonBox:
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        help_btn = cast(QtWidgets.QAbstractButton, buttons.addButton("Help", QtWidgets.QDialogButtonBox.HelpRole))
        help_btn.clicked.connect(self._show_help)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        return buttons

    def _connect_signals(self) -> None:
        self.chk_gentle.toggled.connect(self._on_gentle_toggled)
        self.spin_parallel.valueChanged.connect(self._mark_custom)
        self.txt_headers.textChanged.connect(self._on_header_text_changed)
        self.edit_cookies.textChanged.connect(self._mark_custom)
        self.txt_custom_extraction.textChanged.connect(self._mark_custom)
        self.btn_preset_standard.toggled.connect(lambda checked: checked and self._apply_preset("standard"))
        self.btn_preset_gentle.toggled.connect(lambda checked: checked and self._apply_preset("gentle"))
        self.btn_preset_custom.toggled.connect(lambda checked: checked and self._sync_state())

    def _initialize_options(self, options: CrawlOptions) -> None:
        self.chk_gentle.setChecked(options.gentle_mode)
        self.spin_parallel.setValue(options.max_concurrent_per_host or 2)
        if self.chk_ssr_parity.isEnabled():
            self.chk_ssr_parity.setChecked(options.ssr_parity_check)
        else:
            self.chk_ssr_parity.setChecked(False)
        self.chk_bot_render.setChecked(self.chk_bot_render.isEnabled() and options.bot_render)
        self.chk_render_js.setChecked(self.chk_render_js.isEnabled() and options.render_js)
        self.chk_tech_stack.setChecked(options.tech_stack_detection)
        self.chk_topic_embeddings.setChecked(self.chk_topic_embeddings.isEnabled() and options.topic_embeddings)
        self.chk_allow_insecure_tls.setChecked(options.allow_insecure_tls)
        self.chk_allow_private_network.setChecked(options.allow_private_network)
        profile_index = self.profile_combo.findData(options.profile.value)
        self.profile_combo.setCurrentIndex(profile_index if profile_index >= 0 else 0)
        self._initialize_semrush()
        self._initialize_ai_engines()
        self._load_from_options(options)
        self._sync_state()
        self._apply_sized_geometry()

    def _apply_sized_geometry(self) -> None:
        """Size to the content but never taller/wider than the screen (minus
        headroom for title bar + taskbar), so the button row stays visible."""
        target = self.sizeHint().expandedTo(self.minimumSize())
        screen = self.screen() or QtWidgets.QApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            target.setHeight(min(target.height(), max(self.minimumHeight(), available.height() - 80)))
            target.setWidth(min(target.width(), max(self.minimumWidth(), available.width() - 80)))
        self.resize(target)

    def _initialize_semrush(self) -> None:
        """Prefill the masked key from the keychain and the cap from
        QSettings. Both degrade to empty/default when unavailable."""
        self.edit_semrush_key.setText(self._load_semrush_key())
        settings = self._app_settings()
        self.spin_semrush_max_calls.setValue(int(settings.value("semrush/max_calls", 100) or 100))

    @staticmethod
    def _app_settings() -> QtCore.QSettings:
        """Single seam for the app-wide settings store. The (org, app)
        constructor always uses the platform-native backend (the Windows
        registry) regardless of QSettings.setDefaultFormat, so tests must
        substitute a temp-file store here."""
        return QtCore.QSettings("Silentfrog", "Silentfrog")

    @staticmethod
    def _load_semrush_key() -> str:
        from .integrations.semrush.client import resolve_api_key

        try:
            return resolve_api_key()
        except Exception:
            return ""

    def _initialize_ai_engines(self) -> None:
        """Prefill each masked BYO key from the keychain/env. Degrades to
        empty per field when neither is available."""
        for engine, edit in self.edit_sov_keys.items():
            edit.setText(self._load_sov_key(engine))

    @staticmethod
    def _load_sov_key(engine: str) -> str:
        from .integrations.ai_engines import resolve_api_key

        try:
            return resolve_api_key(engine)
        except Exception:
            return ""

    @staticmethod
    def _checkbox_stylesheet(theme: str) -> str:
        base = "#1f1f1f" if theme == "dark" else "#ffffff"
        border = "rgba(90,90,90,0.8)" if theme == "dark" else "#b5b5b5"
        return (
            "QCheckBox::indicator { width:16px; height:16px; border:1px solid "
            f"{border}; border-radius:3px; background:{base}; }}"
            "QCheckBox::indicator:checked { background:#2ecc71; border:1px solid #2ecc71; }"
        )

    @staticmethod
    def _field_stylesheet(theme: str) -> str:
        base = "#1e1e1e" if theme == "dark" else "#ffffff"
        text = "#f0f0f0" if theme == "dark" else "#202124"
        border = "rgba(90,90,90,0.7)" if theme == "dark" else "#b5b5b5"
        return (
            "QPlainTextEdit, QLineEdit {"
            f" border: 1px solid {border}; border-radius: 4px; padding: 4px;"
            f" background: {base}; color: {text}; }}"
            "QPlainTextEdit:focus, QLineEdit:focus { border: 1px solid #2ecc71; }"
        )

    def _load_from_options(self, options: CrawlOptions) -> bool:
        headers_lines = [f"{key}: {value}" for key, value in options.extra_headers.items() if key.lower() != "cookie"]
        headers_text = "\n".join(headers_lines)
        cookie_text = options.extra_headers.get("Cookie", "")
        extraction_text = options.custom_extraction.to_text()
        advanced_on = bool(headers_text or cookie_text or extraction_text)
        self.txt_headers.setPlainText(headers_text)
        self.edit_cookies.setText(cookie_text)
        self.txt_custom_extraction.setPlainText(extraction_text)
        self._select_initial_preset(options, advanced_on)
        self._validate_headers()
        return advanced_on

    def _sync_state(self) -> None:
        is_gentle = self.chk_gentle.isChecked()
        self.spin_parallel.setEnabled(is_gentle)

    def _on_gentle_toggled(self, checked: bool) -> None:
        if self._applying_preset:
            return
        if not checked:
            self._apply_preset("standard")
        self._sync_state()

    def _mark_custom(self) -> None:
        if self._applying_preset:
            return
        self.btn_preset_custom.setChecked(True)
        self._sync_state()

    def _on_header_text_changed(self) -> None:
        self._mark_custom()
        self._validate_headers()

    def _validate_headers(self) -> None:
        styles = {"invalid": "color:#d32f2f;", "valid": "color:#2e7d32;", "empty": ""}
        text = self.txt_headers.toPlainText().strip()
        if not text:
            self.headers_label.setStyleSheet(styles["empty"])
            return
        _, invalid = parse_header_lines(text)
        state = "invalid" if invalid else "valid"
        self.headers_label.setStyleSheet(styles[state])

    def options(self) -> CrawlOptions:
        header_text = self.txt_headers.toPlainText().strip()
        cookie_text = self.edit_cookies.text().strip()
        ssr = bool(self.chk_ssr_parity.isEnabled() and self.chk_ssr_parity.isChecked())
        bot_render = bool(self.chk_bot_render.isEnabled() and self.chk_bot_render.isChecked())
        return CrawlOptions.from_ui(
            gentle_mode=self.chk_gentle.isChecked(),
            max_parallel=self.spin_parallel.value(),
            header_text=header_text,
            cookie_text=cookie_text,
            ssr_parity_check=ssr,
            bot_render=bot_render,
            render_js=bool(self.chk_render_js.isEnabled() and self.chk_render_js.isChecked()),
            custom_rules_text=self.txt_custom_extraction.toPlainText(),
            tech_stack_detection=self.chk_tech_stack.isChecked(),
            topic_embeddings=bool(self.chk_topic_embeddings.isEnabled() and self.chk_topic_embeddings.isChecked()),
            # Hidden selector (single-page) keeps the incoming profile (DEEP).
            profile=self.profile_combo.currentData(),
            allow_insecure_tls=self.chk_allow_insecure_tls.isChecked(),
            allow_private_network=self.chk_allow_private_network.isChecked(),
        )

    def accept(self) -> None:
        """Persist the Semrush key + AI-engine BYO keys to the keychain and
        the Semrush daily cap to QSettings, then close. Persistence
        failures never block accept."""
        self._persist_semrush()
        self._persist_ai_engine_keys()
        super().accept()

    def _persist_semrush(self) -> None:
        key = self.edit_semrush_key.text().strip()
        settings = self._app_settings()
        settings.setValue("semrush/max_calls", self.spin_semrush_max_calls.value())
        try:
            import keyring

            keyring.set_password("silentfrog-semrush", "api_key", key)
        except Exception:
            # keyring is optional; without it the key falls back to env only.
            return

    def _persist_ai_engine_keys(self) -> None:
        """Persist each non-empty BYO key to the OS keychain only — never to
        QSettings or disk. Swallows when keyring is unavailable, same as
        ``_persist_semrush``."""
        try:
            import keyring
        except Exception:
            # keyring is optional; without it the keys fall back to env only.
            return
        for engine, edit in self.edit_sov_keys.items():
            key = edit.text().strip()
            if not key:
                continue
            try:
                keyring.set_password("silentfrog-ai-engines", engine, key)
            except Exception:
                continue

    def _on_semrush_test(self) -> None:
        """Run test_connection off the UI thread and show ✓/✗. Tiny by
        design — mirrors the app's daemon-thread pattern (see workers.py)."""
        import asyncio
        import threading

        from .integrations.semrush.client import test_connection

        key = self.edit_semrush_key.text().strip()
        self.lbl_semrush_test.setText("Testing…")

        def _target() -> None:
            try:
                ok, message = asyncio.run(test_connection(key))
            except Exception as exc:  # noqa: BLE001
                ok, message = False, str(exc)
            mark = "✓" if ok else "✗"
            QtCore.QMetaObject.invokeMethod(
                self.lbl_semrush_test,
                "setText",
                QtCore.Qt.ConnectionType.QueuedConnection,
                QtCore.Q_ARG(str, f"{mark} {message}"),
            )

        threading.Thread(target=_target, daemon=True).start()

    def _on_sov_test(self) -> None:
        """Test every keyed engine off the UI thread and show a combined
        'engine: message' summary. Mirrors ``_on_semrush_test``'s
        daemon-thread + QueuedConnection pattern; clicking is the consent
        for these on-demand probes, no extra gate."""
        import asyncio
        import threading

        keys = {engine: edit.text().strip() for engine, edit in self.edit_sov_keys.items()}
        self.lbl_sov_test.setText("Testing…")

        def _target() -> None:
            try:
                summary = asyncio.run(_summarize_sov_test(keys))
            except Exception as exc:  # noqa: BLE001
                summary = str(exc)
            QtCore.QMetaObject.invokeMethod(
                self.lbl_sov_test,
                "setText",
                QtCore.Qt.ConnectionType.QueuedConnection,
                QtCore.Q_ARG(str, summary),
            )

        threading.Thread(target=_target, daemon=True).start()

    def _apply_preset(self, preset: str) -> None:
        if self._applying_preset:
            return
        presets = {
            "standard": {"gentle": False, "parallel": 4},
            "gentle": {"gentle": True, "parallel": 2},
            "custom": None,
        }
        config = presets.get(preset)
        self._applying_preset = True
        if config is None:
            self.btn_preset_custom.setChecked(True)
        else:
            self.chk_gentle.setChecked(config["gentle"])
            self.spin_parallel.setValue(config["parallel"])
            self.btn_preset_standard.setChecked(preset == "standard")
            self.btn_preset_gentle.setChecked(preset == "gentle")
        self._applying_preset = False
        self._sync_state()

    def _select_initial_preset(self, options: CrawlOptions, advanced_on: bool) -> None:
        self._applying_preset = True
        if not options.gentle_mode and not advanced_on and options.max_concurrent_per_host >= 4:
            self.btn_preset_standard.setChecked(True)
        elif options.gentle_mode and options.max_concurrent_per_host <= 2 and not advanced_on:
            self.btn_preset_gentle.setChecked(True)
        else:
            self.btn_preset_custom.setChecked(True)
        self._applying_preset = False

    def _show_help(self) -> None:
        QtWidgets.QMessageBox.information(
            self,
            "Gentle crawl mode",
            (
                "Gentle mode keeps the request rate low, respects Crawl-delay directives, "
                "and retries politely after 403/429 responses.\n\n"
                "Use presets for quick defaults or switch to Custom to fine-tune headers and cookies."
            ),
        )
