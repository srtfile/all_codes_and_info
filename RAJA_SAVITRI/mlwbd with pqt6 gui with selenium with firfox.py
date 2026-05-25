"""
Auto Downloader GUI — Complete Resolution & Quality Selector
==========================================================
PyQt6 GUI with support for:
- Language selection (Hindi, Tamil, Dual Audio)
- Quality selection (480p, 720p, 1080p)
- Source selection (GDrive, GDS, MEGA)
- HEVC/H.264 toggle

REQUIREMENTS:
    pip install PyQt6 selenium webdriver-manager

USAGE:
    python auto_downloader_gui.py
"""

import os
import sys
import time
import json
import re
import platform
import subprocess
from datetime import datetime
from threading import Thread
from urllib.parse import urlparse, parse_qs

# ── auto-install deps ─────────────────────────────────────────────────────────
def ensure(pkg, import_as=None):
    name = import_as or pkg.replace("-", "_")
    try:
        __import__(name)
    except ImportError:
        print(f"  Installing {pkg} ...")
        subprocess.check_call([sys.executable, "-m", "pip", "install",
                               pkg, "-q", "--disable-pip-version-check"])

ensure("PyQt6")
ensure("selenium")
ensure("webdriver_manager")
ensure("beautifulsoup4", "bs4")
ensure("requests")

from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                              QHBoxLayout, QLabel, QLineEdit, QPushButton, 
                              QTextEdit, QProgressBar, QGroupBox, QMessageBox,
                              QFrame, QRadioButton, QButtonGroup, QComboBox,
                              QCheckBox, QGridLayout, QScrollArea)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QFont, QPalette, QColor, QIcon
from selenium import webdriver
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service as FirefoxService
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.firefox import GeckoDriverManager
from bs4 import BeautifulSoup
import requests

# ─────────────────────────────────────────────────────────────────────────────
# LINK EXTRACTOR (Pattern matching from HTML)
# ─────────────────────────────────────────────────────────────────────────────
class LinkExtractor:
    def __init__(self):
        self.patterns = {
            'gdrive': r'GDrive',
            'gds': r'GDS',
            'mega': r'MEGA'
        }
    
    def extract_links_from_html(self, html_content, language, quality, source, is_hevc=False):
        """
        Extract specific download link based on criteria
        """
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Language mapping
        lang_map = {
            'Hindi': 'HQ Hindi Dub',
            'Tamil': 'Tamil [Leaked WEB-DL]',
            'Dual Audio': 'Dual Audio'
        }
        
        quality_map = {
            '480p': '480p',
            '720p': '720p',
            '1080p': '1080p',
            'HEVC 720p': 'HEVC 720p',
            'HEVC 1080p': 'HEVC 1080p'
        }
        
        # Build search text based on selection
        if is_hevc and '720p' in quality:
            search_quality = 'HEVC 720p'
        elif is_hevc and '1080p' in quality:
            search_quality = 'HEVC 1080p'
        else:
            search_quality = quality
        
        # Find language section
        lang_section = None
        for header in soup.find_all(['p', 'div', 'blockquote']):
            if lang_map.get(language) and lang_map[language] in header.get_text():
                lang_section = header.find_parent()
                break
        
        if not lang_section:
            # Try to find by scanning all text
            for elem in soup.find_all(['p', 'div']):
                if lang_map.get(language) and lang_map[language] in elem.get_text():
                    lang_section = elem
                    break
        
        if lang_section:
            # Find quality section
            quality_pattern = f"{search_quality}"
            quality_elem = None
            
            for elem in lang_section.find_all(['p', 'div', 'strong']):
                if quality_pattern in elem.get_text():
                    quality_elem = elem
                    break
            
            if quality_elem:
                # Find links within this quality section
                links = quality_elem.find_all('a', href=True)
                for link in links:
                    link_text = link.get_text()
                    if source == 'GDrive' and 'GDrive' in link_text:
                        return link['href']
                    elif source == 'GDS' and 'GDS' in link_text:
                        return link['href']
                    elif source == 'MEGA' and 'MEGA' in link_text:
                        return link['href']
        
        return None

# ─────────────────────────────────────────────────────────────────────────────
# WORKER THREAD
# ─────────────────────────────────────────────────────────────────────────────
class DownloadWorker(QThread):
    status_updated = pyqtSignal(str)
    step_completed = pyqtSignal(int, str)
    final_link_ready = pyqtSignal(str)
    error_occurred = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, target_url, language, quality, source, is_hevc):
        super().__init__()
        self.target_url = target_url
        self.language = language
        self.quality = quality
        self.source = source
        self.is_hevc = is_hevc
        self.driver = None
        self.extractor = LinkExtractor()

    def run(self):
        try:
            self.run_download_chain()
        except Exception as e:
            self.error_occurred.emit(str(e))
        finally:
            self.finished.emit()

    def log(self, message, step=None):
        if step:
            self.step_completed.emit(step, message)
        else:
            self.status_updated.emit(message)

    # ── PROFILE LOADER ─────────────────────────────────────────────────────────
    def get_firefox_profile(self):
        if platform.system() == "Windows":
            base = os.path.join(os.environ["APPDATA"], "Mozilla", "Firefox")
        elif platform.system() == "Darwin":
            base = os.path.expanduser("~/Library/Application Support/Firefox")
        else:
            base = os.path.expanduser("~/.mozilla/firefox")

        ini = os.path.join(base, "profiles.ini")
        self.log(f"Reading profiles.ini: {ini}")
        
        if not os.path.exists(ini):
            raise FileNotFoundError(f"profiles.ini not found at: {ini}")

        profile_rel = None
        with open(ini, "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("Default=") and "Profiles/" in line:
                    profile_rel = line.strip().split("=", 1)[1]
                    break

        if not profile_rel:
            with open(ini, "r", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("Default=") and ("." in line or "/" in line):
                        val = line.strip().split("=", 1)[1]
                        if val and val not in ("0", "1"):
                            profile_rel = val
                            break

        if not profile_rel:
            raise Exception(
                "Could not find Firefox profile path in profiles.ini.\n"
                f"Please open {ini} and check which line starts with 'Default='"
            )

        profile_path = os.path.join(base, profile_rel.replace("/", os.sep))
        profile_path = os.path.normpath(profile_path)

        if not os.path.isdir(profile_path):
            raise FileNotFoundError(
                f"Profile directory does not exist: {profile_path}\n"
                f"Raw value from profiles.ini: {profile_rel}"
            )
        return profile_path

    # ── KILL FIREFOX ───────────────────────────────────────────────────────────
    def kill_firefox(self):
        self.log("Closing any running Firefox...")
        if platform.system() == "Windows":
            os.system("taskkill /F /IM firefox.exe /T >nul 2>&1")
        else:
            os.system("pkill -9 -f firefox 2>/dev/null; true")
        time.sleep(3)

    # ── HELPERS ────────────────────────────────────────────────────────────────
    def page_ready(self, driver, timeout=15):
        for _ in range(int(timeout / 0.3)):
            try:
                if driver.execute_script("return document.readyState;") == "complete":
                    return True
            except:
                return False
            time.sleep(0.3)
        return False

    def switch_to_latest_tab(self, driver):
        handles = driver.window_handles
        driver.switch_to.window(handles[-1])
        self.page_ready(driver, 15)
        time.sleep(2)
        return driver.current_url

    def get_page_html(self, driver):
        """Get current page HTML for link extraction"""
        return driver.page_source

    def wait_and_click(self, driver, by, selector, step_label, timeout=20):
        try:
            el = WebDriverWait(driver, timeout).until(
                EC.presence_of_element_located((by, selector))
            )
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
            time.sleep(0.4)
            el.click()
            self.log(f"Clicked [{selector}]", step_label)
            return True
        except Exception as e:
            self.log(f"FAILED to click [{selector}] — {e}", step_label)
            return False

    def js_click(self, driver, selector_js, step_label):
        try:
            driver.execute_script(selector_js)
            self.log(f"JS click executed", step_label)
            return True
        except Exception as e:
            self.log(f"JS click FAILED — {e}", step_label)
            return False

    def extract_target_link_from_page(self, driver):
        """Extract the specific download link from technews24.site page"""
        self.log(f"Extracting {self.quality} {self.source} link for {self.language}...")
        
        html = self.get_page_html(driver)
        
        # Build quality string based on selection
        quality_str = self.quality
        if self.is_hevc and '720p' in self.quality:
            quality_str = 'HEVC 720p'
        elif self.is_hevc and '1080p' in self.quality:
            quality_str = 'HEVC 1080p'
        
        # Language mapping for HTML
        lang_map = {
            'Hindi': 'HQ Hindi Dub',
            'Tamil': 'Tamil [Leaked WEB-DL]',
            'Dual Audio': 'Dual Audio'
        }
        
        # Parse HTML to find the right link
        soup = BeautifulSoup(html, 'html.parser')
        
        # Find the language section
        target_link = None
        
        # Method 1: Find language header
        lang_headers = soup.find_all(['p', 'h2', 'h3', 'blockquote'])
        current_section = None
        
        for i, header in enumerate(lang_headers):
            header_text = header.get_text()
            if lang_map[self.language] in header_text:
                # Found language section, look ahead
                for j in range(i, min(i + 10, len(lang_headers))):
                    section = lang_headers[j]
                    section_text = section.get_text()
                    
                    # Check if we've moved to next language section
                    if j > i and any(lang in section_text for lang in ['Hindi', 'Tamil', 'Dual']):
                        break
                    
                    # Check for quality
                    if quality_str in section_text:
                        # Find links in this section
                        links = section.find_all('a', href=True)
                        for link in links:
                            link_text = link.get_text()
                            if self.source == 'GDrive' and 'GDrive' in link_text:
                                target_link = link['href']
                                break
                            elif self.source == 'GDS' and 'GDS' in link_text:
                                target_link = link['href']
                                break
                            elif self.source == 'MEGA' and 'MEGA' in link_text:
                                target_link = link['href']
                                break
                        
                        if target_link:
                            break
                
                if target_link:
                    break
        
        # Method 2: Direct search if method 1 fails
        if not target_link:
            all_links = soup.find_all('a', href=True)
            for link in all_links:
                parent_text = link.find_parent('p')
                if parent_text:
                    parent_content = parent_text.get_text()
                    if lang_map[self.language] in parent_content and quality_str in parent_content:
                        link_text = link.get_text()
                        if self.source == 'GDrive' and 'GDrive' in link_text:
                            target_link = link['href']
                            break
                        elif self.source == 'GDS' and 'GDS' in link_text:
                            target_link = link['href']
                            break
                        elif self.source == 'MEGA' and 'MEGA' in link_text:
                            target_link = link['href']
                            break
        
        if target_link:
            self.log(f"Found target link: {target_link[:100]}...")
            return target_link
        else:
            self.log(f"Could not find {self.quality} {self.source} link for {self.language}")
            return None

    # ── MAIN DOWNLOAD CHAIN ────────────────────────────────────────────────────
    def run_download_chain(self):
        STEP_DELAY = 3.0
        WAIT_TIMEOUT = 20

        # ── Setup Firefox ──────────────────────────────────────────────────────
        self.log("Loading Firefox profile...")
        profile_path = self.get_firefox_profile()
        self.log(f"Profile: {profile_path}")

        self.kill_firefox()

        self.log("Initializing GeckoDriver...")
        gecko = GeckoDriverManager().install()

        options = Options()
        options.add_argument("-profile")
        options.add_argument(profile_path)

        self.log("Launching Firefox...")
        svc = FirefoxService(gecko, log_output=subprocess.DEVNULL)
        self.driver = webdriver.Firefox(service=svc, options=options)
        self.driver.maximize_window()
        self.log("Firefox launched (uBlock Origin active)")

        # ── STEP 1 ──────────────────────────────────────────────────────────────
        self.log("STEP 1 — fojik.com → click Download (form submit)", 1)
        self.driver.get(self.target_url)
        self.page_ready(self.driver, 20)
        time.sleep(3)

        submitted = self.js_click(
            self.driver,
            "document.getElementById('113240').submit();",
            1
        )
        if not submitted:
            # Try alternative selectors
            try:
                download_btns = self.driver.find_elements(By.XPATH, "//a[contains(@href, 'javascript')]")
                for btn in download_btns:
                    if 'submit' in btn.get_attribute('href'):
                        btn.click()
                        break
            except:
                pass

        time.sleep(STEP_DELAY)
        cur_url = self.switch_to_latest_tab(self.driver)
        self.log(f"Now at: {cur_url}", 1)

        # ── STEP 2 ──────────────────────────────────────────────────────────────
        self.log("STEP 2 — sharelink-1.shop → click .myButton", 2)
        ok = self.wait_and_click(self.driver, By.CSS_SELECTOR, "button.myButton", 2)
        if not ok:
            ok = self.wait_and_click(self.driver, By.CSS_SELECTOR, "button[type='submit']", 2)
        if not ok:
            self.wait_and_click(self.driver, By.CSS_SELECTOR, ".btn", 2)

        time.sleep(STEP_DELAY)
        cur_url = self.switch_to_latest_tab(self.driver)
        self.log(f"Now at: {cur_url}", 2)

        # ── STEP 3 ──────────────────────────────────────────────────────────────
        self.log("STEP 3 — freethemesy.com → click .download-text", 3)
        ok = self.wait_and_click(self.driver, By.CSS_SELECTOR, "span.download-text", 3)
        if not ok:
            ok = self.wait_and_click(self.driver, By.CSS_SELECTOR, ".download-button", 3)
        if not ok:
            self.wait_and_click(
                self.driver,
                By.XPATH,
                "//*[contains(text(),'Download')]",
                3
            )

        time.sleep(STEP_DELAY)
        cur_url = self.switch_to_latest_tab(self.driver)
        self.log(f"Now at: {cur_url}", 3)

        # ── STEP 4 — Extract the specific link from technews24.site ─────────────
        self.log("STEP 4 — technews24.site → extracting target link", 4)
        
        # First, let the page load completely
        self.page_ready(self.driver, 15)
        time.sleep(2)
        
        # Extract the specific download link based on user selection
        target_link = self.extract_target_link_from_page(self.driver)
        
        if not target_link:
            self.log("Could not find target link, falling back to manual click", 4)
            # Fallback: Try to click GDS link as before
            ok = self.wait_and_click(
                self.driver,
                By.XPATH,
                "/html/body/div[3]/div[1]/div[1]/main[1]/article[1]/div[2]/div[1]/p[5]/strong[1]/a[2]",
                4
            )
            if not ok:
                self.wait_and_click(
                    self.driver,
                    By.XPATH,
                    "//a[contains(@href,'go.php')]",
                    4
                )
            time.sleep(STEP_DELAY)
            cur_url = self.switch_to_latest_tab(self.driver)
            self.log(f"Now at: {cur_url}", 4)
        else:
            # Navigate to the specific link
            self.log(f"Navigating to: {target_link[:80]}...", 4)
            self.driver.get(target_link)
            time.sleep(STEP_DELAY)
            cur_url = self.switch_to_latest_tab(self.driver)
            self.log(f"Now at download page", 4)

        # ── STEP 5 ──────────────────────────────────────────────────────────────
        self.log("STEP 5 — sharelink-3.shop → click generate button", 5)
        ok = self.wait_and_click(self.driver, By.CSS_SELECTOR, "a.butt.btn", 5)
        if not ok:
            ok = self.wait_and_click(
                self.driver,
                By.XPATH,
                "//a[contains(@onclick,'generateDownloadLink')]",
                5
            )
        if not ok:
            self.wait_and_click(
                self.driver,
                By.XPATH,
                "//button[contains(text(),'Generate')]",
                5
            )

        time.sleep(STEP_DELAY)
        cur_url = self.switch_to_latest_tab(self.driver)
        self.log(f"Now at: {cur_url}", 5)

        # ── STEP 6 ──────────────────────────────────────────────────────────────
        self.log("STEP 6 — Click final download button", 6)
        ok = self.wait_and_click(self.driver, By.CSS_SELECTOR, "button[name='submit']", 6)
        if not ok:
            ok = self.wait_and_click(self.driver, By.CSS_SELECTOR, "button.btn-primary", 6)
        if not ok:
            self.wait_and_click(
                self.driver,
                By.XPATH,
                "//button[contains(.,'Download') or contains(.,'Direct Link')]",
                6
            )
        if not ok:
            # Try to find any download link
            download_links = self.driver.find_elements(By.XPATH, "//a[contains(@href, 'download') or contains(@href, 'go.php')]")
            for link in download_links:
                try:
                    link.click()
                    break
                except:
                    pass

        time.sleep(STEP_DELAY)
        try:
            final_url = self.switch_to_latest_tab(self.driver)
        except:
            final_url = self.driver.current_url

        self.log(f"Final URL: {final_url}", 6)
        self.final_link_ready.emit(final_url)

# ─────────────────────────────────────────────────────────────────────────────
# MAIN GUI WINDOW
# ─────────────────────────────────────────────────────────────────────────────
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.worker = None
        self.init_ui()
        self.apply_styles()

    def init_ui(self):
        self.setWindowTitle("Auto Downloader — Complete Edition")
        self.setMinimumSize(900, 800)
        
        # Central widget with scroll
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(15)
        
        # Header
        header_label = QLabel("🎬 Auto Downloader — Complete Edition 🎬")
        header_font = QFont("Arial", 18, QFont.Weight.Bold)
        header_label.setFont(header_font)
        header_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(header_label)
        
        subtitle = QLabel("Raja Shivaji 2026 — Multi-Format Download Chain")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle_font = QFont("Arial", 10)
        subtitle.setFont(subtitle_font)
        main_layout.addWidget(subtitle)
        
        # URL Input Group
        url_group = QGroupBox("Movie URL")
        url_layout = QVBoxLayout()
        
        url_h_layout = QHBoxLayout()
        url_label = QLabel("Enter URL:")
        url_label.setFixedWidth(80)
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("https://fojik.com/movie/jana-nayagan-2026/")
        self.url_input.setText("https://fojik.com/movie/jana-nayagan-2026/")
        
        url_h_layout.addWidget(url_label)
        url_h_layout.addWidget(self.url_input)
        url_layout.addLayout(url_h_layout)
        
        url_group.setLayout(url_layout)
        main_layout.addWidget(url_group)
        
        # Selection Options Group (Grid Layout)
        selection_group = QGroupBox("📋 Download Options")
        selection_layout = QGridLayout()
        
        # Language Selection
        lang_label = QLabel("🎙️ Language:")
        lang_label.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        selection_layout.addWidget(lang_label, 0, 0)
        
        self.language_group = QButtonGroup()
        self.lang_hindi = QRadioButton("🇮🇳 Hindi (HQ Hindi Dub)")
        self.lang_tamil = QRadioButton("🇮🇳 Tamil")
        self.lang_dual = QRadioButton("🎧 Dual Audio")
        self.lang_hindi.setChecked(True)
        
        self.language_group.addButton(self.lang_hindi)
        self.language_group.addButton(self.lang_tamil)
        self.language_group.addButton(self.lang_dual)
        
        lang_layout = QVBoxLayout()
        lang_layout.addWidget(self.lang_hindi)
        lang_layout.addWidget(self.lang_tamil)
        lang_layout.addWidget(self.lang_dual)
        selection_layout.addLayout(lang_layout, 0, 1)
        
        # Quality Selection
        quality_label = QLabel("📺 Quality:")
        quality_label.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        selection_layout.addWidget(quality_label, 0, 2)
        
        self.quality_combo = QComboBox()
        self.quality_combo.addItems(["480p", "720p", "1080p"])
        self.quality_combo.setCurrentText("1080p")
        selection_layout.addWidget(self.quality_combo, 0, 3)
        
        # HEVC Toggle
        self.hevc_check = QCheckBox("🎬 HEVC (x265) — Smaller file size")
        self.hevc_check.setStyleSheet("color: #FFD700;")
        selection_layout.addWidget(self.hevc_check, 1, 0, 1, 2)
        
        # Source Selection
        source_label = QLabel("💾 Source/Hoster:")
        source_label.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        selection_layout.addWidget(source_label, 2, 0)
        
        self.source_group = QButtonGroup()
        self.src_gdrive = QRadioButton("☁️ GDrive")
        self.src_gds = QRadioButton("⚡ GDS")
        self.src_mega = QRadioButton("🔐 MEGA")
        self.src_gdrive.setChecked(True)
        
        self.source_group.addButton(self.src_gdrive)
        self.source_group.addButton(self.src_gds)
        self.source_group.addButton(self.src_mega)
        
        source_layout = QHBoxLayout()
        source_layout.addWidget(self.src_gdrive)
        source_layout.addWidget(self.src_gds)
        source_layout.addWidget(self.src_mega)
        selection_layout.addLayout(source_layout, 2, 1, 1, 3)
        
        selection_group.setLayout(selection_layout)
        main_layout.addWidget(selection_group)
        
        # Info Display for selected options
        self.info_label = QLabel("Selection: 1080p | GDrive | Hindi")
        self.info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.info_label.setStyleSheet("background-color: #2d2d2d; padding: 8px; border-radius: 5px; color: #4CAF50;")
        main_layout.addWidget(self.info_label)
        
        # Update info when selection changes
        self.quality_combo.currentTextChanged.connect(self.update_info)
        self.hevc_check.stateChanged.connect(self.update_info)
        self.lang_hindi.toggled.connect(self.update_info)
        self.lang_tamil.toggled.connect(self.update_info)
        self.lang_dual.toggled.connect(self.update_info)
        self.src_gdrive.toggled.connect(self.update_info)
        self.src_gds.toggled.connect(self.update_info)
        self.src_mega.toggled.connect(self.update_info)
        
        # Control Buttons
        button_layout = QHBoxLayout()
        self.download_btn = QPushButton("🚀 START DOWNLOAD")
        self.download_btn.setMinimumHeight(50)
        self.download_btn.clicked.connect(self.start_download)
        
        self.copy_btn = QPushButton("📋 Copy Link")
        self.copy_btn.setMinimumHeight(50)
        self.copy_btn.clicked.connect(self.copy_link)
        self.copy_btn.setEnabled(False)
        
        self.clear_btn = QPushButton("🗑️ Clear Log")
        self.clear_btn.setMinimumHeight(50)
        self.clear_btn.clicked.connect(self.clear_log)
        
        button_layout.addWidget(self.download_btn)
        button_layout.addWidget(self.copy_btn)
        button_layout.addWidget(self.clear_btn)
        main_layout.addLayout(button_layout)
        
        # Progress Bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 6)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("Step %v/6")
        self.progress_bar.setMinimumHeight(25)
        main_layout.addWidget(self.progress_bar)
        
        # Status Label
        self.status_label = QLabel("Ready — Configure options above")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        status_font = QFont("Arial", 10)
        self.status_label.setFont(status_font)
        main_layout.addWidget(self.status_label)
        
        # Log Output
        log_group = QGroupBox("📝 Process Log")
        log_layout = QVBoxLayout()
        
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setFont(QFont("Consolas", 9))
        log_layout.addWidget(self.log_output)
        
        log_group.setLayout(log_layout)
        main_layout.addWidget(log_group)
        
        # Final Link Display
        link_group = QGroupBox("🎯 FINAL DOWNLOAD LINK")
        link_layout = QVBoxLayout()
        
        self.final_link_text = QTextEdit()
        self.final_link_text.setReadOnly(True)
        self.final_link_text.setMaximumHeight(80)
        self.final_link_text.setFont(QFont("Consolas", 9))
        link_layout.addWidget(self.final_link_text)
        
        link_group.setLayout(link_layout)
        main_layout.addWidget(link_group)
        
        # Footer
        footer = QLabel("Auto Downloader — Powered by Selenium & PyQt6 | Supports: GDrive, GDS, MEGA")
        footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        footer_font = QFont("Arial", 8)
        footer.setFont(footer_font)
        main_layout.addWidget(footer)

    def update_info(self):
        """Update info display when selections change"""
        language = "Hindi" if self.lang_hindi.isChecked() else "Tamil" if self.lang_tamil.isChecked() else "Dual Audio"
        quality = self.quality_combo.currentText()
        source = "GDrive" if self.src_gdrive.isChecked() else "GDS" if self.src_gds.isChecked() else "MEGA"
        hevc_text = " (HEVC)" if self.hevc_check.isChecked() else ""
        
        info_text = f"Selection: {quality}{hevc_text} | {source} | {language}"
        self.info_label.setText(info_text)

    def apply_styles(self):
        # Modern dark theme with better styling
        self.setStyleSheet("""
            QMainWindow {
                background-color: #1a1a2e;
            }
            QGroupBox {
                font-weight: bold;
                border: 2px solid #16213e;
                border-radius: 8px;
                margin-top: 12px;
                padding-top: 12px;
                color: #e2e2e2;
                background-color: #0f3460;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 8px 0 8px;
                color: #e94560;
            }
            QLabel {
                color: #e2e2e2;
            }
            QLineEdit {
                padding: 10px;
                border: 2px solid #16213e;
                border-radius: 8px;
                background-color: #1a1a2e;
                color: #e2e2e2;
                font-size: 12px;
            }
            QLineEdit:focus {
                border-color: #e94560;
            }
            QComboBox {
                padding: 8px;
                border: 2px solid #16213e;
                border-radius: 8px;
                background-color: #1a1a2e;
                color: #e2e2e2;
                min-width: 100px;
            }
            QComboBox::drop-down {
                border: none;
            }
            QComboBox::down-arrow {
                image: none;
                border-left: 5px solid transparent;
                border-right: 5px solid transparent;
                border-top: 5px solid #e2e2e2;
                margin-right: 5px;
            }
            QRadioButton {
                color: #e2e2e2;
                spacing: 8px;
            }
            QRadioButton::indicator {
                width: 16px;
                height: 16px;
                border-radius: 8px;
                border: 2px solid #16213e;
                background-color: #1a1a2e;
            }
            QRadioButton::indicator:checked {
                background-color: #e94560;
                border-color: #e94560;
            }
            QCheckBox {
                color: #FFD700;
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
                border-radius: 4px;
                border: 2px solid #16213e;
                background-color: #1a1a2e;
            }
            QCheckBox::indicator:checked {
                background-color: #e94560;
                border-color: #e94560;
            }
            QPushButton {
                padding: 10px;
                border: none;
                border-radius: 8px;
                background-color: #e94560;
                color: white;
                font-weight: bold;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #ff6b6b;
            }
            QPushButton:pressed {
                background-color: #c81d4e;
            }
            QPushButton:disabled {
                background-color: #555555;
                color: #888888;
            }
            QTextEdit {
                border: 2px solid #16213e;
                border-radius: 8px;
                background-color: #0f0f1a;
                color: #00ff9d;
                font-family: Consolas, monospace;
            }
            QProgressBar {
                border: 2px solid #16213e;
                border-radius: 8px;
                text-align: center;
                color: white;
                background-color: #1a1a2e;
            }
            QProgressBar::chunk {
                background-color: #e94560;
                border-radius: 6px;
            }
        """)

    def add_log(self, message, color=None):
        timestamp = datetime.now().strftime("%H:%M:%S")
        if color:
            colored_msg = f'<span style="color:{color};">[{timestamp}] {message}</span>'
        else:
            colored_msg = f'[{timestamp}] {message}'
        
        self.log_output.append(colored_msg)
        scrollbar = self.log_output.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def clear_log(self):
        self.log_output.clear()
        self.add_log("Log cleared")

    def update_step(self, step, message):
        self.progress_bar.setValue(step)
        self.status_label.setText(f"Step {step}/6: {message}")
        self.add_log(f"✓ Step {step}: {message}", "#4CAF50")

    def update_status(self, message):
        self.status_label.setText(message)
        self.add_log(f"ℹ {message}", "#888888")
    
    def show_error(self, error_msg):
        self.add_log(f"✗ ERROR: {error_msg}", "#f44336")
        QMessageBox.critical(self, "Error", f"An error occurred:\n{error_msg}")
        self.download_btn.setEnabled(True)
        self.download_btn.setText("🚀 START DOWNLOAD")

    def start_download(self):
        url = self.url_input.text().strip()
        
        if not url:
            QMessageBox.warning(self, "Warning", "Please enter a URL")
            return
        
        if not url.startswith("http"):
            QMessageBox.warning(self, "Warning", "Please enter a valid URL (starting with http:// or https://)")
            return
        
        # Get selections
        language = "Hindi" if self.lang_hindi.isChecked() else "Tamil" if self.lang_tamil.isChecked() else "Dual Audio"
        quality = self.quality_combo.currentText()
        source = "GDrive" if self.src_gdrive.isChecked() else "GDS" if self.src_gds.isChecked() else "MEGA"
        is_hevc = self.hevc_check.isChecked()
        
        # Confirm with user
        confirm_msg = f"Starting download with:\n\n• Language: {language}\n• Quality: {quality}{' (HEVC)' if is_hevc else ''}\n• Source: {source}\n\nProceed?"
        reply = QMessageBox.question(self, "Confirm Download", confirm_msg, 
                                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        
        if reply != QMessageBox.StandardButton.Yes:
            return
        
        # Disable controls
        self.download_btn.setEnabled(False)
        self.download_btn.setText("⏳ PROCESSING...")
        self.copy_btn.setEnabled(False)
        self.progress_bar.setValue(0)
        self.final_link_text.clear()
        
        # Clear log
        self.log_output.clear()
        self.add_log(f"🎯 Target: {quality}{' (HEVC)' if is_hevc else ''} | {source} | {language}")
        self.add_log("=" * 60)
        
        # Start worker thread
        self.worker = DownloadWorker(url, language, quality, source, is_hevc)
        self.worker.step_completed.connect(self.update_step)
        self.worker.status_updated.connect(self.update_status)
        self.worker.final_link_ready.connect(self.on_final_link_ready)
        self.worker.error_occurred.connect(self.show_error)
        self.worker.finished.connect(self.on_worker_finished)
        
        self.worker.start()
    
    def on_final_link_ready(self, link):
        self.final_link_text.setText(link)
        self.add_log("=" * 60, "#FFD700")
        self.add_log(f"✅ FINAL DOWNLOAD LINK READY ✅", "#4CAF50")
        self.add_log(f"📎 {link}", "#2196F3")
        self.add_log("=" * 60, "#FFD700")
        self.copy_btn.setEnabled(True)
        self.status_label.setText("✅ Complete — Link ready to copy")
    
    def on_worker_finished(self):
        self.download_btn.setEnabled(True)
        self.download_btn.setText("🚀 START DOWNLOAD")
    
    def copy_link(self):
        link = self.final_link_text.toPlainText().strip()
        if link:
            clipboard = QApplication.clipboard()
            clipboard.setText(link)
            self.add_log("📋 Link copied to clipboard!", "#2196F3")
            QMessageBox.information(self, "Copied", "Download link copied to clipboard!")
        else:
            QMessageBox.warning(self, "Warning", "No link to copy")

# ─────────────────────────────────────────────────────────────────────────────
# MAIN ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────
def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    
    window = MainWindow()
    window.show()
    
    sys.exit(app.exec())

if __name__ == "__main__":
    main()  