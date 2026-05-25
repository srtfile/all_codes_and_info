#!/usr/bin/env python3
"""
MITM Network Analyser  v2.0  —  Advanced PyQt6 Desktop GUI
===========================================================
One-click proxy start/stop. Captures everything DevTools can see.
Auto-saves full session to timestamped folder on stop.
"""

import json, os, subprocess, sys, time, re, shutil
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from PyQt6.QtCore import (Qt, QThread, pyqtSignal, QAbstractTableModel,
                           QModelIndex, QTimer, QSortFilterProxyModel)
from PyQt6.QtGui  import QColor, QFont, QSyntaxHighlighter, QTextCharFormat, QBrush
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QLineEdit, QTabWidget, QTableView, QTextEdit,
    QSplitter, QComboBox, QStatusBar, QHeaderView, QMessageBox,
    QSpinBox, QTreeWidget, QTreeWidgetItem, QFrame, QProgressBar,
    QCheckBox, QFileDialog, QGroupBox, QScrollArea, QAbstractItemView
)

BASE_DIR   = Path(__file__).parent
JSONL_FILE = BASE_DIR / "mitm_captured.jsonl"
ADDON_FILE = BASE_DIR / "mitm_toolkit.py"
SAVE_DIR   = BASE_DIR / "captures"

# ── Colours ───────────────────────────────────────────────────────────────────
TYPE_COL = {
    "xhr/api":"#4fc3f7","html":"#a5d6a7","js":"#fff176","css":"#ce93d8",
    "image":"#ffcc80","media":"#ef9a9a","font":"#b0bec5","sse":"#80deea",
    "ws":"#80cbc4","binary":"#ff8a65","text":"#e0e0e0","other":"#757575",
}
METHOD_COL = {
    "GET":"#66bb6a","POST":"#42a5f5","PUT":"#ffa726",
    "DELETE":"#ef5350","PATCH":"#ab47bc","OPTIONS":"#78909c","HEAD":"#26a69a",
}
STATUS_COL = {2:"#66bb6a",3:"#ffa726",4:"#ef5350",5:"#b71c1c"}

DARK = """
QMainWindow,QWidget{background:#0f0f1a;color:#e0e0e0;
  font-family:'Segoe UI',Consolas,monospace;font-size:13px;}
QTableView{background:#141428;gridline-color:#1e1e3a;
  selection-background-color:#1a3a5c;border:1px solid #1e1e3a;}
QHeaderView::section{background:#1a1a2e;color:#80cbc4;padding:5px;
  border:none;font-weight:bold;font-size:12px;}
QTextEdit,QPlainTextEdit{background:#0d0d1f;color:#c8e6c9;
  border:1px solid #1e1e3a;font-family:Consolas,monospace;font-size:12px;}
QTabWidget::pane{border:1px solid #1e1e3a;background:#0f0f1a;}
QTabBar::tab{background:#1a1a2e;color:#78909c;padding:7px 16px;
  border-radius:4px 4px 0 0;margin-right:2px;}
QTabBar::tab:selected{background:#0d0d1f;color:#80cbc4;border-bottom:2px solid #4fc3f7;}
QLineEdit,QSpinBox,QComboBox{background:#1a1a2e;color:#e0e0e0;
  border:1px solid #2a2a4e;border-radius:4px;padding:4px 8px;}
QComboBox QAbstractItemView{background:#1a1a2e;color:#e0e0e0;
  selection-background-color:#1a3a5c;}
QStatusBar{background:#080814;color:#80cbc4;font-size:12px;}
QSplitter::handle{background:#1e1e3a;}
QLabel{color:#90a4ae;}
QTreeWidget{background:#141428;color:#e0e0e0;border:1px solid #1e1e3a;}
QTreeWidget::item:selected{background:#1a3a5c;}
QScrollBar:vertical{background:#0f0f1a;width:8px;}
QScrollBar::handle:vertical{background:#2a2a4e;border-radius:4px;}
QPushButton{border-radius:5px;padding:4px 10px;}
QGroupBox{border:1px solid #1e1e3a;border-radius:6px;
  margin-top:8px;color:#80cbc4;font-weight:bold;}
QGroupBox::title{subcontrol-origin:margin;left:10px;padding:0 4px;}
"""

# ── JSON Syntax Highlighter ───────────────────────────────────────────────────
class JsonHighlighter(QSyntaxHighlighter):
    def __init__(self, doc):
        super().__init__(doc)
        self._rules = []
        def _fmt(color, bold=False):
            f = QTextCharFormat()
            f.setForeground(QColor(color))
            if bold: f.setFontWeight(QFont.Weight.Bold)
            return f
        self._rules = [
            (re.compile(r'"[^"\\]*(?:\\.[^"\\]*)*"\s*:'), _fmt("#80cbc4", True)),
            (re.compile(r':\s*"[^"\\]*(?:\\.[^"\\]*)*"'),  _fmt("#a5d6a7")),
            (re.compile(r'\b(true|false|null)\b'),           _fmt("#ffcc80")),
            (re.compile(r'\b-?\d+\.?\d*([eE][+-]?\d+)?\b'), _fmt("#ce93d8")),
        ]
    def highlightBlock(self, text):
        for pat, fmt in self._rules:
            for m in pat.finditer(text):
                self.setFormat(m.start(), m.end()-m.start(), fmt)

# ── Traffic Table Model ───────────────────────────────────────────────────────
COLS = ["#","Time","Method","Status","Type","Host","Path","Size","ms","Auth","TLS"]

class TrafficModel(QAbstractTableModel):
    def __init__(self):
        super().__init__()
        self._all  = []
        self._view = []

    def rowCount(self, p=QModelIndex()): return len(self._view)
    def columnCount(self, p=QModelIndex()): return len(COLS)

    def headerData(self, s, o, role=Qt.ItemDataRole.DisplayRole):
        if role==Qt.ItemDataRole.DisplayRole and o==Qt.Orientation.Horizontal:
            return COLS[s]

    def data(self, idx, role=Qt.ItemDataRole.DisplayRole):
        if not idx.isValid(): return None
        r = self._view[idx.row()]
        c = idx.column()
        url = r.get("url","")
        parsed = urlparse(url)

        if role == Qt.ItemDataRole.DisplayRole:
            vals = [
                str(r.get("_n","")),
                (r.get("ts","") or "")[11:19],
                r.get("method", r.get("type","")),
                str(r.get("status","")),
                r.get("resource_type","other"),
                r.get("host", parsed.netloc),
                parsed.path[:70],
                _sz(r.get("body_size") or r.get("_size",0)),
                str(r.get("timing_ms","")),
                "🔑" if r.get("auth_found") else "",
                "🔒" if r.get("tls") else "",
            ]
            return vals[c]

        if role == Qt.ItemDataRole.ForegroundRole:
            if c==2: return QColor(METHOD_COL.get(r.get("method",""),"#e0e0e0"))
            if c==3:
                s = r.get("status",0)
                return QColor(STATUS_COL.get(s//100 if isinstance(s,int) else 0,"#e0e0e0"))
            if c==4: return QColor(TYPE_COL.get(r.get("resource_type","other"),"#e0e0e0"))
            if c==9: return QColor("#ffcc80")
            return QColor("#c0c0d0")

        if role == Qt.ItemDataRole.BackgroundRole:
            return QColor("#141428" if idx.row()%2==0 else "#111122")
        return None

    def add(self, rows):
        if not rows: return
        pos = len(self._view)
        self.beginInsertRows(QModelIndex(), pos, pos+len(rows)-1)
        self._all.extend(rows)
        self._view.extend(rows)
        self.endInsertRows()

    def filter(self, text, rtype, method):
        tl = text.lower()
        self.beginResetModel()
        self._view = [
            r for r in self._all
            if (not tl or tl in r.get("url","").lower() or tl in r.get("host","").lower())
            and (rtype=="all" or r.get("resource_type","other")==rtype)
            and (method=="ALL" or r.get("method","")==method)
        ]
        self.endResetModel()

    def clear(self):
        self.beginResetModel()
        self._all.clear(); self._view.clear()
        self.endResetModel()

    def row(self, i):
        return self._view[i] if 0<=i<len(self._view) else {}

    def all_rows(self): return list(self._all)

def _sz(n):
    if not n: return ""
    n=int(n)
    if n<1024: return f"{n}B"
    if n<1048576: return f"{n//1024}K"
    return f"{n//1048576}M"

# ── JSONL Watcher Thread ──────────────────────────────────────────────────────
class Watcher(QThread):
    got = pyqtSignal(list)
    def __init__(self, path):
        super().__init__()
        self._path=path; self._stop=False; self._off=0; self._n=0
    def reset(self): self._off=0; self._n=0
    def stop(self):  self._stop=True
    def run(self):
        self._stop=False
        while not self._stop:
            try:
                if self._path.exists():
                    with self._path.open("r",encoding="utf-8") as fh:
                        fh.seek(self._off)
                        batch=[]
                        for line in fh:
                            line=line.strip()
                            if not line: continue
                            try:
                                rec=json.loads(line)
                                self._n+=1
                                rec["_n"]=self._n
                                rec["_size"]=len(line)
                                batch.append(rec)
                            except: pass
                        self._off=fh.tell()
                        if batch: self.got.emit(batch)
            except: pass
            time.sleep(0.4)

# ── Stats panel ───────────────────────────────────────────────────────────────
class StatsPanel(QWidget):
    def __init__(self):
        super().__init__()
        self._counts = defaultdict(int)
        lay = QVBoxLayout(self)
        lay.setSpacing(4)

        self._lbl_total   = self._mk("Total Records", "0")
        self._lbl_req     = self._mk("Requests",      "0")
        self._lbl_resp    = self._mk("Responses",     "0")
        self._lbl_auth    = self._mk("Auth Tokens",   "0")
        self._lbl_cookies = self._mk("Cookies",       "0")
        self._lbl_m3u8    = self._mk("M3U8 Playlists","0")
        self._lbl_ws      = self._mk("WS Frames",     "0")
        self._lbl_js      = self._mk("JS Files",      "0")
        self._lbl_html    = self._mk("HTML Pages",    "0")
        self._lbl_xhr     = self._mk("XHR/API",       "0")
        self._lbl_media   = self._mk("Media",         "0")
        self._lbl_hosts   = self._mk("Unique Hosts",  "0")
        self._lbl_crypto  = self._mk("🔐 Crypto in JS","0")
        self._lbl_enc     = self._mk("🔒 Enc Payloads","0")
        self._lbl_gql     = self._mk("GraphQL Ops",   "0")

        for w in [self._lbl_total,self._lbl_req,self._lbl_resp,
                  self._lbl_auth,self._lbl_cookies,self._lbl_m3u8,
                  self._lbl_ws,self._lbl_js,self._lbl_html,
                  self._lbl_xhr,self._lbl_media,self._lbl_hosts,
                  self._lbl_crypto,self._lbl_enc,self._lbl_gql]:
            lay.addWidget(w)
        lay.addStretch()

    def _mk(self, label, val):
        w = QFrame()
        w.setStyleSheet("background:#1a1a2e;border-radius:6px;padding:2px;")
        h = QHBoxLayout(w)
        h.setContentsMargins(8,4,8,4)
        lbl = QLabel(label); lbl.setStyleSheet("color:#78909c;font-size:12px;")
        val_lbl = QLabel(val); val_lbl.setStyleSheet("color:#80cbc4;font-weight:bold;font-size:14px;")
        val_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        h.addWidget(lbl); h.addStretch(); h.addWidget(val_lbl)
        w._val = val_lbl
        return w

    def update_from(self, rows):
        reqs  = [r for r in rows if r.get("type")=="request"]
        resps = [r for r in rows if r.get("type")=="response"]
        ws    = [r for r in rows if r.get("type")=="ws_frame"]
        auth  = sum(1 for r in reqs if r.get("auth_found"))
        ck    = sum(len(r.get("set_cookies",[])) for r in resps)
        m3u8  = sum(1 for r in resps if r.get("m3u8"))
        js    = sum(1 for r in resps if r.get("resource_type")=="js")
        html  = sum(1 for r in resps if r.get("resource_type")=="html")
        xhr   = sum(1 for r in reqs  if r.get("resource_type")=="xhr/api")
        media = sum(1 for r in reqs  if r.get("resource_type")=="media")
        hosts = len({r.get("host","") for r in reqs})

        self._lbl_total._val.setText(str(len(rows)))
        self._lbl_req._val.setText(str(len(reqs)))
        self._lbl_resp._val.setText(str(len(resps)))
        self._lbl_auth._val.setText(str(auth))
        self._lbl_cookies._val.setText(str(ck))
        self._lbl_m3u8._val.setText(str(m3u8))
        self._lbl_ws._val.setText(str(len(ws)))
        self._lbl_js._val.setText(str(js))
        self._lbl_html._val.setText(str(html))
        self._lbl_xhr._val.setText(str(xhr))
        self._lbl_media._val.setText(str(media))
        self._lbl_hosts._val.setText(str(hosts))
        self._lbl_crypto._val.setText(str(sum(1 for r in resps if r.get("crypto"))))
        self._lbl_enc._val.setText(str(sum(1 for r in rows if r.get("enc_payload"))))
        self._lbl_gql._val.setText(str(sum(1 for r in reqs if r.get("graphql"))))

# ── Main Window ───────────────────────────────────────────────────────────────
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("MITM Network Analyser  v2.0")
        self.resize(1600, 950)
        self._proc    = None
        self._model   = TrafficModel()
        self._watcher = Watcher(JSONL_FILE)
        self._watcher.got.connect(self._on_records)
        self._stats_timer = QTimer()
        self._stats_timer.timeout.connect(self._refresh_stats)
        self._build_ui()
        self.setStyleSheet(DARK)
        self._sb("Ready  —  click  ▶ Start Proxy  to begin")

    # ── Build UI ──────────────────────────────────────────────────────────────
    def _build_ui(self):
        cw = QWidget(); self.setCentralWidget(cw)
        root = QVBoxLayout(cw); root.setSpacing(5); root.setContentsMargins(6,6,6,6)

        # ── Toolbar ──
        tb = QHBoxLayout(); tb.setSpacing(6)

        self._btn_start = self._btn("▶  Start Proxy","#2e7d32","#fff",42,self._start)
        self._btn_stop  = self._btn("■  Stop","#555","#888",42,self._stop,False)
        self._btn_clear = self._btn("🗑  Clear","#37474f","#ccc",38,self._clear)
        self._btn_webui = self._btn("🌐  Web UI","#1565c0","#fff",38,
                                    lambda: os.startfile("http://127.0.0.1:8081/"))
        self._btn_save  = self._btn("💾  Save Now","#4a148c","#fff",38,self._save_now)
        self._btn_open  = self._btn("📂  Open Saves","#00695c","#fff",38,
                                    lambda: os.startfile(str(SAVE_DIR)))

        lp=QLabel("Port:"); self._port=QSpinBox()
        self._port.setRange(1024,65535); self._port.setValue(8080); self._port.setFixedWidth(75)

        lf=QLabel("Filter:"); self._filt=QLineEdit()
        self._filt.setPlaceholderText("regex URL filter  (default: .*)"); self._filt.setFixedWidth(200)

        self._lbl_n = QLabel("0 records")
        self._lbl_n.setStyleSheet("color:#4fc3f7;font-weight:bold;font-size:14px;")
        self._lbl_save = QLabel("")
        self._lbl_save.setStyleSheet("color:#a5d6a7;font-size:11px;")

        for w in [self._btn_start,self._btn_stop,self._btn_clear,
                  self._btn_webui,self._btn_save,self._btn_open]:
            tb.addWidget(w)
        tb.addSpacing(10)
        tb.addWidget(lp); tb.addWidget(self._port)
        tb.addSpacing(6)
        tb.addWidget(lf); tb.addWidget(self._filt)
        tb.addStretch()
        tb.addWidget(self._lbl_save)
        tb.addWidget(self._lbl_n)
        root.addLayout(tb)

        # ── Filter bar ──
        fb = QHBoxLayout(); fb.setSpacing(8)
        fb.addWidget(QLabel("Search:"))
        self._search = QLineEdit(); self._search.setPlaceholderText("URL / host / path…")
        self._search.textChanged.connect(self._refilter)
        fb.addWidget(self._search,1)

        fb.addWidget(QLabel("Type:"))
        self._type_cb = QComboBox()
        self._type_cb.addItems(["all","xhr/api","html","js","css","image",
                                 "media","font","sse","binary","ws","other"])
        self._type_cb.currentTextChanged.connect(self._refilter)
        fb.addWidget(self._type_cb)

        fb.addWidget(QLabel("Method:"))
        self._meth_cb = QComboBox()
        self._meth_cb.addItems(["ALL","GET","POST","PUT","DELETE","PATCH","OPTIONS","HEAD"])
        self._meth_cb.currentTextChanged.connect(self._refilter)
        fb.addWidget(self._meth_cb)

        self._chk_auth = QCheckBox("Auth only")
        self._chk_auth.stateChanged.connect(self._refilter)
        self._chk_auth.setStyleSheet("color:#ffcc80;")
        fb.addWidget(self._chk_auth)
        root.addLayout(fb)

        # ── Main horizontal splitter: stats | traffic+detail ──
        h_split = QSplitter(Qt.Orientation.Horizontal)

        # Left: stats panel
        self._stats_panel = StatsPanel()
        self._stats_panel.setFixedWidth(200)
        h_split.addWidget(self._stats_panel)

        # Right: vertical splitter traffic table | detail tabs
        v_split = QSplitter(Qt.Orientation.Vertical)

        # Traffic table
        self._table = QTableView()
        self._table.setModel(self._model)
        self._table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableView.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.setShowGrid(False)
        self._table.setAlternatingRowColors(False)
        hh = self._table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        hh.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)
        for i,w in enumerate([40,70,70,55,70,0,0,55,55,30,30]):
            if w: self._table.setColumnWidth(i,w)
        self._table.selectionModel().currentRowChanged.connect(self._on_select)
        v_split.addWidget(self._table)

        # Detail tabs (8 tabs)
        self._dtabs = QTabWidget()
        self._t_req   = QTextEdit(); self._t_req.setReadOnly(True)
        self._t_resp  = QTextEdit(); self._t_resp.setReadOnly(True)
        self._t_hdrs  = QTextEdit(); self._t_hdrs.setReadOnly(True)
        self._t_cook  = QTextEdit(); self._t_cook.setReadOnly(True)
        self._t_m3u8  = QTextEdit(); self._t_m3u8.setReadOnly(True)
        self._t_ws    = QTextEdit(); self._t_ws.setReadOnly(True)
        self._t_raw   = QTextEdit(); self._t_raw.setReadOnly(True)
        self._t_curl  = QTextEdit(); self._t_curl.setReadOnly(True)

        for hl in [self._t_resp, self._t_req, self._t_raw]:
            JsonHighlighter(hl.document())

        self._t_crypto = QTextEdit(); self._t_crypto.setReadOnly(True)
        self._t_payload= QTextEdit(); self._t_payload.setReadOnly(True)

        self._dtabs.addTab(self._t_req,    "📤 Request")
        self._dtabs.addTab(self._t_resp,   "📥 Response")
        self._dtabs.addTab(self._t_hdrs,   "🔤 Headers")
        self._dtabs.addTab(self._t_cook,   "🍪 Cookies")
        self._dtabs.addTab(self._t_m3u8,   "📺 M3U8/Media")
        self._dtabs.addTab(self._t_ws,     "🔌 WebSocket")
        self._dtabs.addTab(self._t_raw,    "📄 Raw Body")
        self._dtabs.addTab(self._t_curl,   "⚡ cURL")
        self._dtabs.addTab(self._t_crypto, "🔐 Crypto")
        self._dtabs.addTab(self._t_payload,"🔒 Enc Payload")
        v_split.addWidget(self._dtabs)
        v_split.setSizes([520,300])

        h_split.addWidget(v_split)
        h_split.setSizes([200,1400])
        root.addWidget(h_split,1)

        # ── Bottom: analysis tabs ──
        self._atabs = QTabWidget()
        self._atabs.setFixedHeight(280)

        self._a_apis    = QTextEdit(); self._a_apis.setReadOnly(True)
        self._a_auth    = QTextEdit(); self._a_auth.setReadOnly(True)
        self._a_media   = QTextEdit(); self._a_media.setReadOnly(True)
        self._a_crypto  = QTextEdit(); self._a_crypto.setReadOnly(True)
        self._a_payload = QTextEdit(); self._a_payload.setReadOnly(True)
        self._a_cookies = QTreeWidget()
        self._a_cookies.setHeaderLabels(["Domain","Name","Value","Secure","HttpOnly"])
        self._a_cookies.setColumnWidth(0,160); self._a_cookies.setColumnWidth(1,140)
        self._a_cookies.setColumnWidth(2,300)

        # JS Search tab
        js_search_w = QWidget()
        js_lay = QVBoxLayout(js_search_w); js_lay.setContentsMargins(4,4,4,4); js_lay.setSpacing(4)
        js_bar = QHBoxLayout()
        self._js_search = QLineEdit(); self._js_search.setPlaceholderText("Search across all captured JS… (encrypt, AES, token, api, fetch…)")
        js_btn = QPushButton("🔍 Search"); js_btn.setFixedWidth(90)
        js_btn.setStyleSheet("background:#1a3a5c;color:#80cbc4;border-radius:4px;")
        js_btn.clicked.connect(self._search_js)
        self._js_search.returnPressed.connect(self._search_js)
        js_bar.addWidget(self._js_search,1); js_bar.addWidget(js_btn)
        self._js_results = QTextEdit(); self._js_results.setReadOnly(True)
        js_lay.addLayout(js_bar); js_lay.addWidget(self._js_results,1)

        self._atabs.addTab(self._a_apis,    "🔗 API Endpoints")
        self._atabs.addTab(self._a_auth,    "🔑 Auth Vault")
        self._atabs.addTab(self._a_media,   "📺 All Media URLs")
        self._atabs.addTab(self._a_cookies, "🍪 Cookie Jar")
        self._atabs.addTab(self._a_crypto,  "🔐 Crypto in JS")
        self._atabs.addTab(self._a_payload, "🔒 Enc Payloads")
        self._atabs.addTab(js_search_w,     "🔍 JS Search")

        # Refresh buttons
        abar = QHBoxLayout()
        for label,fn in [("↻ APIs",self._refresh_apis),
                         ("↻ Auth",self._refresh_auth),
                         ("↻ Media",self._refresh_media),
                         ("↻ Cookies",self._refresh_cookies),
                         ("↻ Crypto",self._refresh_crypto),
                         ("↻ Enc Payloads",self._refresh_payloads),
                         ("📋 Postman",self._export_postman),
                         ("📋 cURLs",self._export_curls),
                         ("💾 Save All Now",self._save_now)]:
            b=QPushButton(label)
            b.setFixedHeight(26)
            col = "#4a148c" if "Save" in label else "#1a2a3a"
            b.setStyleSheet(f"background:{col};color:#80cbc4;font-size:11px;border-radius:4px;")
            b.clicked.connect(fn)
            abar.addWidget(b)
        abar.addStretch()

        ab_wrap = QWidget()
        ab_lay  = QVBoxLayout(ab_wrap); ab_lay.setContentsMargins(0,0,0,0); ab_lay.setSpacing(2)
        ab_lay.addLayout(abar)
        ab_lay.addWidget(self._atabs)
        root.addWidget(ab_wrap)

        self.setStatusBar(QStatusBar())

    # ── Proxy control ─────────────────────────────────────────────────────────
    def _start(self):
        if self._proc and self._proc.poll() is None: return
        port = self._port.value()
        filt = self._filt.text().strip() or ".*"
        env  = os.environ.copy()
        env["MITM_FILTER"]  = filt
        env["MITM_OUTFILE"] = str(JSONL_FILE)
        env["MITM_SAVE_DIR"]= str(SAVE_DIR)
        try:
            self._proc = subprocess.Popen(
                ["mitmweb","--listen-host","127.0.0.1",
                 "--listen-port",str(port),"-s",str(ADDON_FILE)],
                env=env, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, cwd=str(BASE_DIR))
        except FileNotFoundError:
            QMessageBox.critical(self,"Error","mitmweb not found.\npip install mitmproxy")
            return
        self._watcher.reset(); self._watcher.start()
        self._stats_timer.start(2000)
        self._btn_start.setEnabled(False)
        self._btn_start.setStyleSheet("background:#555;color:#888;font-size:14px;border-radius:6px;")
        self._btn_stop.setEnabled(True)
        self._btn_stop.setStyleSheet("background:#c62828;color:#fff;font-weight:bold;font-size:14px;border-radius:6px;")
        self._sb(f"✅ Proxy on 127.0.0.1:{port}  |  Web UI: http://127.0.0.1:8081/  |  Set browser proxy → 127.0.0.1:{port}")

    def _stop(self):
        self._watcher.stop()
        self._stats_timer.stop()
        if self._proc:
            self._proc.terminate(); self._proc=None
        self._btn_start.setEnabled(True)
        self._btn_start.setStyleSheet("background:#2e7d32;color:#fff;font-weight:bold;font-size:14px;border-radius:6px;")
        self._btn_stop.setEnabled(False)
        self._btn_stop.setStyleSheet("background:#555;color:#888;font-size:14px;border-radius:6px;")
        self._sb("⏹ Proxy stopped  —  session auto-saved to captures/ folder")
        # Give toolkit a moment to write, then show save path
        QTimer.singleShot(3000, self._show_latest_save)

    def _show_latest_save(self):
        if SAVE_DIR.exists():
            dirs = sorted(SAVE_DIR.iterdir(), key=lambda d: d.stat().st_mtime, reverse=True)
            if dirs:
                self._lbl_save.setText(f"💾 Saved → {dirs[0].name}")

    def _clear(self):
        self._model.clear()
        self._lbl_n.setText("0 records")
        if JSONL_FILE.exists(): JSONL_FILE.write_text("")
        if self._watcher.isRunning(): self._watcher.reset()
        for w in [self._t_req,self._t_resp,self._t_hdrs,self._t_cook,
                  self._t_m3u8,self._t_ws,self._t_raw,self._t_curl,
                  self._a_apis,self._a_auth,self._a_media]:
            w.clear()
        self._a_cookies.clear()

    def _save_now(self):
        """Manually trigger save without stopping proxy."""
        rows = self._model.all_rows()
        if not rows:
            self._sb("Nothing to save yet."); return
        self._export_session(rows)

    # ── Live records ──────────────────────────────────────────────────────────
    def _on_records(self, batch):
        # apply auth-only filter
        if self._chk_auth.isChecked():
            batch = [r for r in batch if r.get("auth_found")]
        self._model.add(batch)
        self._lbl_n.setText(f"{len(self._model._all)} records")
        last = self._model.index(self._model.rowCount()-1,0)
        self._table.scrollTo(last)

    def _refilter(self):
        auth_only = self._chk_auth.isChecked()
        text  = self._search.text()
        rtype = self._type_cb.currentText()
        meth  = self._meth_cb.currentText()
        self._model.filter(text, rtype, meth)
        if auth_only:
            self._model.beginResetModel()
            self._model._view = [r for r in self._model._view if r.get("auth_found")]
            self._model.endResetModel()

    def _refresh_stats(self):
        self._stats_panel.update_from(self._model._all)

    # ── Row detail ────────────────────────────────────────────────────────────
    def _on_select(self, cur, _):
        r = self._model.row(cur.row())
        if not r: return
        url = r.get("url","")
        method = r.get("method","")
        headers = r.get("headers",{})
        body = r.get("body_raw","") or ""

        # ── Request tab ──
        lines = [f"{method} {url}", f"HTTP/{r.get('http_version','?')}",
                 f"Host: {r.get('host','')}", f"Type: {r.get('resource_type','?')}",
                 f"TLS: {r.get('tls',False)}  SNI: {r.get('tls_sni','')}",
                 f"Referrer: {r.get('referrer','')}",
                 f"Origin: {r.get('origin','')}",
                 f"User-Agent: {r.get('user_agent','')}",
                 ""]
        if r.get("graphql"):
            gql = r["graphql"]
            lines += [f"── GraphQL {gql.get('type','?').upper()} ──",
                      f"Operation: {gql.get('operation','')}",
                      f"Query: {gql.get('query','')}",""]
        if r.get("query"):
            lines += ["── Query Params ──"] + [f"  {k}={v}" for k,v in r["query"].items()] + [""]
        if body:
            try:
                lines += ["── Body ──", json.dumps(json.loads(body),indent=2)[:6000]]
            except:
                lines += ["── Body ──", body[:6000]]
        self._t_req.setPlainText("\n".join(lines))

        # ── Response tab ──
        rlines = [f"Status: {r.get('status','')} {r.get('reason','')}",
                  f"Timing: {r.get('timing_ms','')} ms",
                  f"Content-Type: {r.get('content_type','')}",
                  f"Body size: {_sz(r.get('body_size',0))}",""]
        rb = r.get("body_raw","") or ""
        if rb:
            try:
                rlines += ["── Body ──", json.dumps(json.loads(rb),indent=2)[:12000]]
            except:
                rlines += ["── Body ──", rb[:12000]]
        self._t_resp.setPlainText("\n".join(rlines))

        # ── Headers tab ──
        hlines = []
        if r.get("auth_found"):
            hlines += ["══ AUTH / SESSION HEADERS ══"]
            for k,v in r["auth_found"].items():
                hlines.append(f"  {k}: {v}")
            hlines += [""]
        hlines += ["══ ALL HEADERS ══"]
        for k,v in headers.items():
            hlines.append(f"  {k}: {v}")
        self._t_hdrs.setPlainText("\n".join(hlines))

        # ── Cookies tab ──
        clines = []
        if r.get("cookies"):
            clines += ["══ REQUEST COOKIES ══"]
            for k,v in r["cookies"].items():
                clines.append(f"  {k} = {v}")
            clines += [""]
        if r.get("set_cookies"):
            clines += ["══ SET-COOKIE (Response) ══"]
            for ck in r["set_cookies"]:
                clines.append(f"  {ck.get('name')} = {ck.get('value')}")
                clines.append(f"    domain={ck.get('domain')}  path={ck.get('path')}"
                              f"  secure={ck.get('secure')}  httponly={ck.get('httponly')}"
                              f"  samesite={ck.get('samesite')}  expires={ck.get('expires')}")
        self._t_cook.setPlainText("\n".join(clines) if clines else "No cookies in this record.")

        # ── M3U8 tab ──
        if r.get("m3u8"):
            m = r["m3u8"]
            mlines = [f"M3U8 Playlist: {url}", "",
                      f"Sub-playlists ({len(m.get('sub_playlists',[]))}):",
                      *[f"  {u}" for u in m.get("sub_playlists",[])], "",
                      f"Encryption Keys ({len(m.get('keys',[]))}):",
                      *[f"  {u}" for u in m.get("keys",[])], "",
                      f"Segments ({len(m.get('segments',[]))}):",
                      *[f"  {u}" for u in m.get("segments",[])[:200]]]
            self._t_m3u8.setPlainText("\n".join(mlines))
        else:
            self._t_m3u8.setPlainText("No M3U8 data for this record.\n\n"
                "M3U8 data appears when a .m3u8 playlist is captured.")

        # ── Raw body tab ──
        self._t_raw.setPlainText(body[:20000] if body else rb[:20000])

        # ── cURL tab ──
        skip = {"content-length","transfer-encoding","host"}
        hflags = " \\\n  ".join(f'-H "{k}: {v}"' for k,v in headers.items()
                                  if k.lower() not in skip)
        bflag = ""
        if body:
            esc = body.replace('"','\\"')[:2000]
            bflag = f' \\\n  --data "{esc}"'
        curl = f'curl -X {method} "{url}" \\\n  {hflags}{bflag}'
        self._t_curl.setPlainText(curl)

        # ── Crypto tab ──
        crypto = r.get("crypto") or []
        if crypto:
            clines = [f"🔐 CRYPTO PATTERNS FOUND IN JS: {url}\n","─"*60]
            for f in crypto:
                clines += [f"\n  Pattern : {f['pattern']}",
                           f"  Count   : {f['count']}",
                           f"  Snippet : …{f['snippet']}…"]
            self._t_crypto.setPlainText("\n".join(clines))
        else:
            self._t_crypto.setPlainText("No crypto patterns detected in this resource.\n\n"
                "Crypto tab shows findings when JS files contain:\n"
                "CryptoJS, AES, RSA, window.crypto, btoa/atob, HMAC, SHA, etc.")

        # ── Encrypted Payload tab ──
        enc = (r.get("enc_payload") or [])
        if enc:
            elines = [f"🔒 ENCRYPTED/ENCODED PAYLOAD DETECTED\n","─"*60]
            for f in enc:
                elines += [f"\n  Type   : {f['type']}",
                           f"  Sample : {f['sample']}"]
            self._t_payload.setPlainText("\n".join(elines))
        else:
            self._t_payload.setPlainText("No encrypted payload detected in this record.\n\n"
                "This tab detects: JWT tokens, CryptoJS ciphertext (U2FsdGVkX1…),\n"
                "large base64 blobs, hex strings, encrypted JSON fields.")

    # ── Analysis panels ───────────────────────────────────────────────────────
    def _refresh_apis(self):
        rows = self._model._all
        reqs = [r for r in rows if r.get("type")=="request"]
        apis = {}
        for r in reqs:
            p = urlparse(r["url"])
            key = f"{r['method']} {p.scheme}://{r.get('host','')}{p.path}"
            if key not in apis:
                apis[key] = {"n":0,"auth":bool(r.get("auth_found")),
                             "signed":r.get("signed_url",False),
                             "type":r.get("resource_type","?")}
            apis[key]["n"]+=1
        lines = [f"  {'#':>5}  {'AUTH':5}  {'TYPE':10}  ENDPOINT",
                 "  "+"-"*90]
        for ep,d in sorted(apis.items(),key=lambda x:-x[1]["n"]):
            lines.append(f"  {d['n']:>5}  {'✓' if d['auth'] else '·':5}  "
                         f"{d['type']:10}  {ep}")
        self._a_apis.setPlainText(f"  {len(apis)} unique endpoints\n\n"+"\n".join(lines))
        self._atabs.setCurrentIndex(0)

    def _refresh_auth(self):
        rows = self._model._all
        vault = {}
        for r in rows:
            if r.get("type")=="request" and r.get("auth_found"):
                for k,v in r["auth_found"].items():
                    if k.lower()!="cookie":
                        vault[k]=v
        lines = ["  AUTH TOKENS & API KEYS CAPTURED\n","  "+"-"*70]
        for k,v in vault.items():
            lines.append(f"\n  Header : {k}")
            lines.append(f"  Value  : {v[:200]}{'…' if len(v)>200 else ''}")
        if not vault:
            lines.append("\n  No auth tokens captured yet.")
        self._a_auth.setPlainText("\n".join(lines))
        self._atabs.setCurrentIndex(1)

    def _refresh_media(self):
        rows = self._model._all
        m3u8s, segs, keys, other_media = [], [], [], []
        for r in rows:
            if r.get("type")=="request" and r.get("resource_type")=="media":
                url = r["url"]
                if ".m3u8" in url.lower() or ".m3u" in url.lower():
                    m3u8s.append(url)
                else:
                    other_media.append(url)
            if r.get("type")=="response" and r.get("m3u8"):
                segs.extend(r["m3u8"].get("segments",[]))
                keys.extend(r["m3u8"].get("keys",[]))
                m3u8s.extend(r["m3u8"].get("sub_playlists",[]))
        lines = [f"  M3U8 PLAYLISTS ({len(m3u8s)}):"]
        lines += [f"  {u}" for u in dict.fromkeys(m3u8s)]
        lines += [f"\n  ENCRYPTION KEYS ({len(keys)}):"]
        lines += [f"  {u}" for u in dict.fromkeys(keys)]
        lines += [f"\n  SEGMENTS ({len(segs)}):"]
        lines += [f"  {u}" for u in dict.fromkeys(segs)[:500]]
        lines += [f"\n  OTHER MEDIA ({len(other_media)}):"]
        lines += [f"  {u}" for u in dict.fromkeys(other_media)]
        self._a_media.setPlainText("\n".join(lines))
        self._atabs.setCurrentIndex(2)

    def _refresh_cookies(self):
        self._a_cookies.clear()
        rows = self._model._all
        jar = defaultdict(dict)
        for r in rows:
            if r.get("type")=="response":
                host = r.get("host","?")
                for ck in (r.get("set_cookies") or []):
                    jar[host][ck.get("name","?")] = ck
        for domain, cookies in sorted(jar.items()):
            di = QTreeWidgetItem([domain,"","","",""])
            di.setForeground(0, QColor("#80cbc4"))
            for name, ck in cookies.items():
                ci = QTreeWidgetItem([
                    "", name, ck.get("value","")[:80],
                    "✓" if ck.get("secure") else "",
                    "✓" if ck.get("httponly") else "",
                ])
                ci.setForeground(1, QColor("#fff176"))
                ci.setForeground(2, QColor("#a5d6a7"))
                di.addChild(ci)
            self._a_cookies.addTopLevelItem(di)
            di.setExpanded(True)
        self._atabs.setCurrentIndex(3)

    def _refresh_crypto(self):
        rows = self._model._all
        hits = [(r.get("url",""), r.get("crypto",[])) for r in rows if r.get("crypto")]
        if not hits:
            self._a_crypto.setPlainText("No crypto patterns found yet.\n"
                "Browse pages with JavaScript — CryptoJS, AES, RSA, window.crypto etc. will appear here.")
            self._atabs.setCurrentIndex(4); return
        lines = [f"  🔐 CRYPTO PATTERNS IN JS  ({len(hits)} files)\n","  "+"─"*70]
        for url, findings in hits:
            lines.append(f"\n  {url[:90]}")
            for f in findings:
                lines.append(f"    [{f['pattern']}] ×{f['count']}  …{f['snippet'][:100]}…")
        self._a_crypto.setPlainText("\n".join(lines))
        self._atabs.setCurrentIndex(4)

    def _refresh_payloads(self):
        rows = self._model._all
        hits = [(r.get("url",""), r.get("type",""), r.get("enc_payload",[]))
                for r in rows if r.get("enc_payload")]
        if not hits:
            self._a_payload.setPlainText("No encrypted payloads detected yet.\n"
                "Encrypted payloads (JWT, CryptoJS ciphertext, base64 blobs, hex strings) will appear here.")
            self._atabs.setCurrentIndex(5); return
        lines = [f"  🔒 ENCRYPTED/ENCODED PAYLOADS  ({len(hits)} records)\n","  "+"─"*70]
        for url, rtype, findings in hits:
            lines.append(f"\n  [{rtype}] {url[:90]}")
            for f in findings:
                lines.append(f"    {f['type']}: {f['sample'][:100]}")
        self._a_payload.setPlainText("\n".join(lines))
        self._atabs.setCurrentIndex(5)

    def _search_js(self):
        term = self._js_search.text().strip()
        if not term:
            return
        rows = self._model._all
        js_rows = [r for r in rows if r.get("resource_type")=="js" and r.get("body_raw")]
        results = []
        tl = term.lower()
        for r in js_rows:
            body = r.get("body_raw","")
            if tl in body.lower():
                # find all occurrences with context
                idx = 0
                occurrences = []
                bl = body.lower()
                while True:
                    pos = bl.find(tl, idx)
                    if pos == -1 or len(occurrences) >= 5: break
                    start = max(0, pos-80); end = min(len(body), pos+len(term)+80)
                    occurrences.append(body[start:end].replace("\n"," ").strip())
                    idx = pos + 1
                results.append({"url": r["url"], "count": len(occurrences),
                                 "snippets": occurrences})
        if not results:
            self._js_results.setPlainText(f'No matches for "{term}" in {len(js_rows)} captured JS files.')
            return
        lines = [f'  🔍 "{term}"  →  {sum(r["count"] for r in results)} matches in {len(results)} JS files\n',
                 "  "+"─"*70]
        for r in results:
            lines.append(f"\n  📄 {r['url'][:90]}  ({r['count']} matches)")
            for s in r["snippets"]:
                lines.append(f"     …{s[:160]}…")
        self._js_results.setPlainText("\n".join(lines))
        self._atabs.setCurrentIndex(6)

    # ── Export ────────────────────────────────────────────────────────────────
    def _export_postman(self):
        rows = self._model._all
        reqs = [r for r in rows if r.get("type")=="request"]
        items, seen = [], set()
        for r in reqs:
            key=(r.get("method"),r.get("url"))
            if key in seen: continue
            seen.add(key)
            p=urlparse(r["url"])
            item={"name":f"{r['method']} {p.path or '/'}",
                  "request":{"method":r["method"],
                    "header":[{"key":k,"value":v} for k,v in r.get("headers",{}).items()
                               if k.lower() not in ("content-length","transfer-encoding")],
                    "url":{"raw":r["url"],"protocol":p.scheme,
                           "host":p.netloc.split("."),"path":[x for x in p.path.split("/") if x]}}}
            if r.get("body_raw"):
                item["request"]["body"]={"mode":"raw","raw":r["body_raw"]}
            items.append(item)
        col={"info":{"name":"MITM Capture","schema":
             "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"},
             "item":items}
        out = BASE_DIR/"postman_collection.json"
        out.write_text(json.dumps(col,indent=2,ensure_ascii=False))
        self._sb(f"✅ Postman collection saved → {out}  ({len(items)} requests)")

    def _export_curls(self):
        rows = self._model._all
        reqs = [r for r in rows if r.get("type")=="request"]
        skip = {"content-length","transfer-encoding","host"}
        lines = []
        for r in reqs:
            hf=" \\\n  ".join(f'-H "{k}: {v}"' for k,v in r.get("headers",{}).items()
                               if k.lower() not in skip)
            bf=""
            if r.get("body_raw"):
                esc=r["body_raw"].replace('"','\\"')[:1000]
                bf=f' \\\n  --data "{esc}"'
            lines.append(f'curl -X {r["method"]} "{r["url"]}" \\\n  {hf}{bf}\n')
        out = BASE_DIR/"curl_commands.txt"
        out.write_text("\n".join(lines), encoding="utf-8")
        self._sb(f"✅ cURL commands saved → {out}  ({len(lines)} requests)")

    def _export_session(self, rows):
        """Full save — everything to timestamped folder."""
        ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = SAVE_DIR / ts
        dest.mkdir(parents=True, exist_ok=True)

        reqs  = [r for r in rows if r.get("type")=="request"]
        resps = [r for r in rows if r.get("type")=="response"]
        ws    = [r for r in rows if r.get("type")=="ws_frame"]

        # 1. Full JSONL
        if JSONL_FILE.exists():
            shutil.copy(JSONL_FILE, dest/"full_capture.jsonl")

        # 2. API endpoints
        apis={}
        for r in reqs:
            p=urlparse(r["url"])
            k=f"{r['method']} {p.scheme}://{r.get('host','')}{p.path}"
            if k not in apis: apis[k]={"method":r["method"],"url":k,"count":0,
                                        "auth":bool(r.get("auth_found")),
                                        "type":r.get("resource_type","?")}
            apis[k]["count"]+=1
        (dest/"api_endpoints.json").write_text(json.dumps(list(apis.values()),indent=2,ensure_ascii=False))

        # 3. Auth tokens
        auth={}
        for r in reqs:
            for k,v in (r.get("auth_found") or {}).items():
                if k.lower()!="cookie": auth[k]=v
        (dest/"auth_tokens.json").write_text(json.dumps(auth,indent=2,ensure_ascii=False))

        # 4. Cookies
        jar=defaultdict(dict)
        for r in resps:
            for ck in (r.get("set_cookies") or []):
                jar[r.get("host","?")][ck.get("name","?")] = ck
        (dest/"cookies.json").write_text(json.dumps({d:dict(v) for d,v in jar.items()},indent=2,ensure_ascii=False))

        # 5. All request headers
        (dest/"all_request_headers.json").write_text(
            json.dumps([{"url":r["url"],"method":r["method"],
                         "headers":r.get("headers",{}),"referrer":r.get("referrer",""),
                         "origin":r.get("origin","")} for r in reqs],indent=2,ensure_ascii=False))

        # 6. Media / m3u8 / mpd
        media={"m3u8_playlists":[],"segments":[],"keys":[],"mpd_streams":[]}
        for r in resps:
            if r.get("m3u8"):
                media["m3u8_playlists"].append(r["url"])
                media["segments"].extend(r["m3u8"].get("segments",[]))
                media["keys"].extend(r["m3u8"].get("keys",[]))
            if r.get("mpd"):
                media["mpd_streams"].extend(r["mpd"].get("streams",[]))
        (dest/"media_urls.json").write_text(json.dumps(media,indent=2,ensure_ascii=False))

        # 7. JS files
        js_dir = dest/"js_files"; js_dir.mkdir(exist_ok=True)
        for r in resps:
            if r.get("resource_type")=="js" and r.get("body_raw"):
                p=urlparse(r["url"])
                fname=f"{p.netloc}_{Path(p.path).name or 'index'}"[:60]+".js"
                (js_dir/fname).write_text(r["body_raw"],encoding="utf-8",errors="replace")

        # 8. HTML pages
        html_dir = dest/"html_pages"; html_dir.mkdir(exist_ok=True)
        for r in resps:
            if r.get("resource_type")=="html" and r.get("body_raw"):
                p=urlparse(r["url"])
                fname=f"{p.netloc}_{Path(p.path).name or 'index'}"[:60]+".html"
                (html_dir/fname).write_text(r["body_raw"],encoding="utf-8",errors="replace")

        # 9. XHR/API responses
        xhr_dir = dest/"xhr_responses"; xhr_dir.mkdir(exist_ok=True)
        for r in resps:
            if r.get("resource_type")=="xhr/api" and r.get("body_raw"):
                p=urlparse(r["url"])
                fname=f"{p.netloc}_{Path(p.path).name or 'api'}"[:60]+".json"
                (xhr_dir/fname).write_text(r["body_raw"],encoding="utf-8",errors="replace")

        # 10. XHR/Fetch requests
        xhr_reqs=[{"url":r["url"],"method":r["method"],
                   "headers":r.get("headers",{}),"body":r.get("body_raw","")}
                  for r in reqs if r.get("is_xhr") or r.get("resource_type")=="xhr/api"]
        (dest/"xhr_fetch_requests.json").write_text(json.dumps(xhr_reqs,indent=2,ensure_ascii=False))

        # 11. WebSocket frames
        if ws:
            (dest/"websocket_frames.json").write_text(json.dumps(ws,indent=2,ensure_ascii=False,default=str))

        # 12. Crypto findings
        crypto_hits=[{"url":r["url"],"findings":r["crypto"]} for r in resps if r.get("crypto")]
        if crypto_hits:
            (dest/"crypto_in_js.json").write_text(json.dumps(crypto_hits,indent=2,ensure_ascii=False))

        # 13. Encrypted payloads
        enc_hits=[{"url":r.get("url"),"type":r["type"],"findings":r["enc_payload"]}
                  for r in reqs+resps if r.get("enc_payload")]
        if enc_hits:
            (dest/"encrypted_payloads.json").write_text(json.dumps(enc_hits,indent=2,ensure_ascii=False))

        # 14. GraphQL
        gql=[{"url":r["url"],"graphql":r["graphql"]} for r in reqs if r.get("graphql")]
        if gql:
            (dest/"graphql_operations.json").write_text(json.dumps(gql,indent=2,ensure_ascii=False))

        # 15. Referrer chain
        refs=[{"url":r["url"],"referrer":r.get("referrer",""),"origin":r.get("origin","")}
              for r in reqs if r.get("referrer") or r.get("origin")]
        (dest/"referrer_chain.json").write_text(json.dumps(refs,indent=2,ensure_ascii=False))

        # 16. Summary
        summary={
            "session_ts":ts, "total":len(rows),
            "requests":len(reqs), "responses":len(resps), "ws_frames":len(ws),
            "unique_hosts":len({r.get("host","") for r in reqs}),
            "api_endpoints":len(apis), "auth_tokens":len(auth),
            "js_files":len(list(js_dir.iterdir())),
            "html_pages":len(list(html_dir.iterdir())),
            "xhr_requests":len(xhr_reqs),
            "crypto_js_hits":len(crypto_hits),
            "encrypted_payloads":len(enc_hits),
            "graphql_ops":len(gql),
            "m3u8_playlists":len(media["m3u8_playlists"]),
            "media_segments":len(media["segments"]),
        }
        (dest/"summary.json").write_text(json.dumps(summary,indent=2,ensure_ascii=False))

        self._lbl_save.setText(f"💾 Saved → {dest.name}")
        self._sb(f"✅ Everything saved → {dest.resolve()}  ({len(rows)} records, {len(reqs)} requests)")

    # ── Helpers ───────────────────────────────────────────────────────────────
    def _btn(self, text, bg, fg, h, fn, enabled=True):
        b=QPushButton(text)
        b.setFixedHeight(h)
        b.setEnabled(enabled)
        b.setStyleSheet(f"background:{bg};color:{fg};font-size:13px;border-radius:6px;"
                        f"{'font-weight:bold;' if h>=40 else ''}")
        b.clicked.connect(fn)
        return b

    def _sb(self, msg): self.statusBar().showMessage(msg)

    def closeEvent(self, e):
        self._stop(); e.accept()


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__=="__main__":
    app=QApplication(sys.argv)
    app.setApplicationName("MITM Network Analyser v2.0")
    win=MainWindow()
    win.show()
    sys.exit(app.exec())
