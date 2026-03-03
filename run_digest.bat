@echo off
cd /d C:\Users\khira\canada-consultations

echo. >> digest_log.txt
echo ======================================== >> digest_log.txt
echo Started: %DATE% %TIME% >> digest_log.txt

"C:\Users\khira\canada-consultations\venv\Scripts\python.exe" generate_digest.py >> digest_log.txt 2>&1

echo Finished: %DATE% %TIME% >> digest_log.txt
