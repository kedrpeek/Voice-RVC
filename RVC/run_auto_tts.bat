@echo off
REM -----------------------------------------------------------
REM Batch-file to launch auto_tts.py with frequently used
REM parameters.  Edit the variables below as you wish.
REM -----------------------------------------------------------

REM Change working directory to the folder where the bat resides
pushd "%~dp0"

REM ===== User-editable parameters =====
set "INPUT_TXT=input.txt"      REM текстовый файл-источник
set "OUTPUT_FILE=output.mp3"   REM итоговый аудиофайл (mp3 или wav)
set "FORMAT=mp3"               REM mp3 или wav
set "CHUNK_SIZE=1000"          REM кол-во символов в чанке
set "MAX_WAIT=120"             REM таймаут ожидания загрузки (сек.)
REM ====================================

python auto_tts.py ^
    --input "%INPUT_TXT%" ^
    --out "%OUTPUT_FILE%" ^
    --format %FORMAT% ^
    --chunk-size %CHUNK_SIZE% ^
    --max-wait %MAX_WAIT%

popd
pause 