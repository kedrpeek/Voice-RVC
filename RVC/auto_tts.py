#!/usr/bin/env python3
"""auto_tts.py
Automate voice generation with a local RVC web UI running at http://127.0.0.1:6969/.

Features
--------
1. Reads input text file and splits it into ~``chunk_size`` character chunks, ensuring
   we never break sentences in the middle (splits only after `.`, `?`, or `!`).
2. Uses Selenium (Chrome) to open the RVC webpage, paste each chunk into the text
   field, click the *Generate* button, and wait for the audio file (mp3/wav) to
   download.
3. After all parts are generated, concatenates them in order into a single final
   audio file (mp3 or wav) using *pydub*.

Prerequisites
-------------
- Python 3.8+
- Google Chrome (or Chromium) installed
- FFmpeg available on your ``PATH`` (required by *pydub*)
- Install Python deps:
    pip install selenium webdriver-manager pydub tqdm

Usage
-----
python auto_tts.py \
       --input text.txt \
       --out final.mp3 \
       --format mp3 \
       --chunk-size 1000 \
       --max-wait 120

You **MUST** inspect your RVC webpage (http://127.0.0.1:6969/) and fill in the
correct CSS selectors for ``TEXTAREA_SELECTOR``, ``GENERATE_BTN_SELECTOR`` and
``DOWNLOAD_LINK_SELECTOR`` below. They are *guesses* and will likely need
adjustment to match your local UI.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import List
import stat

from pydub import AudioSegment
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from webdriver_manager.chrome import ChromeDriverManager
from tqdm import tqdm

# ---------------------------------------------------------------------------
# USER: Verify/update these CSS selectors to match your local RVC web UI.
# ---------------------------------------------------------------------------
TEXTAREA_XPATH = '//*[@id="component-353"]/label/div[2]/textarea'
GENERATE_BTN_XPATH = '//*[@id="component-392"]'
DOWNLOAD_ANCHOR_XPATH = '//*[@id="component-395"]/div[2]/a'
DOWNLOAD_BTN_CLICK_XPATH = '//*[@id="component-395"]/div[2]/a/button'
AUDIO_XPATH = '//audio'  # Ищем любой audio элемент на странице
MAIN_AUDIO_XPATH = '//*[@id="waveform"]/div//audio'
HIDDEN_AUDIO_XPATH = '//*[@id="component-395"]/audio'
# ---------------------------------------------------------------------------

URL = "http://127.0.0.1:6969/"

# ---------------- Verbosity helpers ----------------
VERBOSE = True  # Will be set in main() based on --quiet flag

def vprint(*args, **kwargs):
    """Print only when VERBOSE is True."""
    if VERBOSE:
        print(*args, **kwargs)
# ---------------------------------------------------


def split_into_chunks(text: str, chunk_size: int = 1000) -> List[str]:
    """Split *text* into chunks not exceeding *chunk_size*, ending at sentence boundaries.
    Always includes remaining text in the last chunk, even if it's smaller than chunk_size."""
    sentence_end_re = re.compile(r"(?<=[.!?])\s+")
    sentences = sentence_end_re.split(text)

    chunks: List[str] = []
    current_chunk = ""
    for sent in sentences:
        sent = sent.strip()
        if not sent:
            continue
        # +1 for potential space when joining
        if len(current_chunk) + len(sent) + 1 > chunk_size:
            if current_chunk:
                chunks.append(current_chunk.strip())
                current_chunk = sent
            else:
                # Single sentence longer than chunk_size; split brutally
                parts = [sent[i : i + chunk_size] for i in range(0, len(sent), chunk_size)]
                chunks.extend(parts[:-1])
                current_chunk = parts[-1]
        else:
            current_chunk += (" " if current_chunk else "") + sent

    # Всегда добавляем оставшийся текст, даже если он меньше chunk_size
    if current_chunk.strip():
        chunks.append(current_chunk.strip())
    # Если chunks пустой, но есть текст - добавляем весь текст как один чанк
    elif text.strip():
        chunks.append(text.strip())
    return chunks


def setup_browser(download_dir: Path) -> webdriver.Chrome:
    """Configure Chrome WebDriver to connect to existing Chrome instance."""
    chrome_options = Options()
    # Подключаемся к уже запущенному Chrome
    chrome_options.add_experimental_option("debuggerAddress", "127.0.0.1:9222")

    # Настройки для скачивания файлов
    prefs = {
        "download.default_directory": str(download_dir),
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "safebrowsing.enabled": True,
    }
    chrome_options.add_experimental_option("prefs", prefs)

    # Create a Service instance to avoid passing the driver path as positional arg
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)
    # Устанавливаем download directory через DevTools протокол
    try:
        driver.execute_cdp_cmd("Page.setDownloadBehavior", {
            "behavior": "allow",
            "downloadPath": str(download_dir)
        })
        vprint(f"[INFO] Настроил директорию загрузки Chrome: {download_dir}")
    except Exception as e:
        vprint(f"[WARN] Не удалось установить download directory: {e}")
    return driver


def wait_for_new_download(download_dir: Path, known_files: set[str], timeout: int) -> Path:
    """Wait until a new file appears in *download_dir* (not in *known_files*)."""
    start = time.time()
    while time.time() - start < timeout:
        candidates = {f for f in os.listdir(download_dir) if not f.endswith(".crdownload")}
        new_files = candidates - known_files
        if new_files:
            newest = max(new_files, key=lambda f: (download_dir / f).stat().st_mtime)
            return download_dir / newest
        time.sleep(0.5)
    raise TimeoutError("Download did not complete within allotted time")


def generate_audio_chunks(chunks: List[str], fmt: str, max_wait: int) -> Path:
    """Drive browser automation to generate audio files for each *chunks* and return folder path."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    download_dir = Path.cwd() / f"rvc_downloads_{ts}"
    download_dir.mkdir(exist_ok=True)

    driver = setup_browser(download_dir)
    vprint("[INFO] Подключился к существующему Chrome. Убедитесь что RVC открыт на http://127.0.0.1:6969/")

    try:
        for idx, chunk in enumerate(tqdm(chunks, desc="Generating", unit="chunk"), start=1):
            # 1. Находим и заполняем поле ввода
            textarea = WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.XPATH, TEXTAREA_XPATH))
            )
            # Проверяем что элемент видим и кликабелен
            WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.XPATH, TEXTAREA_XPATH))
            )
            driver.execute_script("arguments[0].scrollIntoView(true);", textarea)
            # Используем JavaScript для установки значения textarea
            driver.execute_script("arguments[0].value = '';", textarea)  # Очищаем
            driver.execute_script("arguments[0].value = arguments[1];", textarea, chunk)  # Устанавливаем текст
            # Триггерим событие input для активации обработчиков
            driver.execute_script("arguments[0].dispatchEvent(new Event('input', { bubbles: true }));", textarea)

            # --- ШАГ 2. Подготовка данных для сравнения перед генерацией ---
            # Фиксируем текущее состояние аудио и ссылки download
            def get_attr_safe(xpath, attr):
                try:
                    return driver.find_element(By.XPATH, xpath).get_attribute(attr)
                except Exception:
                    return None

            prev_src_main = get_attr_safe(MAIN_AUDIO_XPATH, "src")
            prev_src_hidden = get_attr_safe(HIDDEN_AUDIO_XPATH, "src")
            prev_href_download = get_attr_safe(DOWNLOAD_ANCHOR_XPATH, "href")

            # 2. Нажимаем кнопку Generate
            gen_btn = driver.find_element(By.XPATH, GENERATE_BTN_XPATH)
            WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.XPATH, GENERATE_BTN_XPATH))
            )
            driver.execute_script("arguments[0].scrollIntoView(true);", gen_btn)
            gen_btn.click()

            # --- ШАГ 3. Ожидаем готовности нового аудио (любое изменение) ---
            vprint(f"[INFO] Жду генерации аудио для части {idx}...")

            def new_audio_ready(_driver):
                try:
                    # Проверяем src у основного аудио
                    cur_main = get_attr_safe(MAIN_AUDIO_XPATH, "src")
                    if cur_main and cur_main != prev_src_main:
                        return True

                    # Проверяем src у скрытого аудио
                    cur_hidden = get_attr_safe(HIDDEN_AUDIO_XPATH, "src")
                    if cur_hidden and cur_hidden != prev_src_hidden:
                        return True

                    # Проверяем ссылку download у якоря
                    cur_href = get_attr_safe(DOWNLOAD_ANCHOR_XPATH, "href")
                    if cur_href and cur_href != prev_href_download:
                        return True
                except Exception:
                    pass
                return False

            try:
                WebDriverWait(driver, 300, poll_frequency=1.0).until(new_audio_ready)
                vprint(f"[INFO] Аудио сгенерировано для части {idx}")
            except TimeoutException:
                raise RuntimeError(f"Audio generation timed out for chunk {idx}")

            # 4. Ждём появления кнопки скачивания и кликаем
            vprint(f"[INFO] Ищу кнопку скачивания для части {idx}...")
            download_btn = WebDriverWait(driver, 60, poll_frequency=1.0).until(
                EC.element_to_be_clickable((By.XPATH, DOWNLOAD_BTN_CLICK_XPATH))
            )
            vprint(f"[INFO] Кнопка скачивания найдена для части {idx}")
            driver.execute_script("arguments[0].scrollIntoView(true);", download_btn)

            # Определяем текущие файлы перед скачиванием
            before_files = {f for f in os.listdir(download_dir)}

            download_btn.click()
            vprint(f"[INFO] Кликнул по кнопке скачивания для части {idx}")

            # 4. Wait for file to land in downloads
            try:
                vprint(f"[INFO] Жду загрузки файла для части {idx}...")
                new_file = wait_for_new_download(download_dir, before_files, timeout=max_wait)
                vprint(f"[INFO] Файл загружен: {new_file.name}")
            except TimeoutError:
                raise RuntimeError(f"Timed out waiting for download for chunk {idx}")

            # Rename to keep order
            ordered_name = f"part_{idx:04d}.{fmt}"
            vprint(f"[INFO] Переименовываю файл в {ordered_name}")
            (download_dir / new_file.name).rename(download_dir / ordered_name)
            vprint(f"[INFO] Часть {idx} завершена успешно")
    finally:
        driver.quit()

    return download_dir


def concatenate_audio(parts_dir: Path, output_path: Path):
    """Concatenate all audio files inside *parts_dir* (sorted) into *output_path*."""
    files = sorted(parts_dir.glob("part_*"), key=lambda p: p.name)
    if not files:
        raise FileNotFoundError("No audio parts found to concatenate")

    combined = AudioSegment.empty()
    for f in files:
        combined += AudioSegment.from_file(f)

    combined.export(output_path, format=output_path.suffix.lstrip("."))
    print(f"[OK] Wrote final audio to {output_path.resolve()}")


def main(argv: List[str] | None = None):
    parser = argparse.ArgumentParser(description="Automate RVC text-to-speech generation")
    parser.add_argument("--input", default="input.txt", help="Path to input text file (default: input.txt in current dir)")
    parser.add_argument("--out", required=True, help="Destination output audio file (mp3/wav)")
    parser.add_argument("--format", choices=["mp3", "wav"], default="mp3", help="Audio format to download & merge")
    parser.add_argument("--chunk-size", type=int, default=1000, help="Approximate characters per chunk (sentence aligned)")
    parser.add_argument("--max-wait", type=int, default=120, help="Seconds to wait for each download")
    parser.add_argument("--quiet", action="store_true", help="Suppress detailed logging")

    args = parser.parse_args(argv)

    # Set global verbosity flag so that helper vprint() knows whether to output
    global VERBOSE
    VERBOSE = not args.quiet

    vprint("[INFO] Жду 3 секунды, переключитесь на окно RVC если нужно...")
    time.sleep(3)

    text_path = Path(args.input)
    if not text_path.is_file():
        parser.error(f"Input file {text_path} does not exist")

    # Read and split input text
    raw_text = text_path.read_text(encoding="utf-8")
    chunks = split_into_chunks(raw_text, chunk_size=args.chunk_size)
    vprint(f"[INFO] Split input into {len(chunks)} chunk(s)")

    # Generate audio for each chunk via browser automation
    parts_dir = generate_audio_chunks(chunks, fmt=args.format, max_wait=args.max_wait)

    # Concatenate parts in order
    output_path = Path(args.out)
    concatenate_audio(parts_dir, output_path)

    # Надёжно очищаем временную папку с частями
    for attempt in range(3):
        try:
            shutil.rmtree(parts_dir, onerror=lambda func, path, exc_info: (
                os.chmod(path, stat.S_IWRITE), func(path)
            ))
            vprint(f"[INFO] Временная папка {parts_dir} удалена")
            break
        except Exception as e:
            vprint(f"[WARN] Не удалось удалить {parts_dir}: {e}")
            if attempt < 2:
                time.sleep(2)
            else:
                vprint(f"[WARN] Оставил временную папку {parts_dir}; удалите вручную")


if __name__ == "__main__":
    main() 