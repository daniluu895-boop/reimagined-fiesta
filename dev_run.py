# dev_run.py — авто-рестарт при изменении файлов
import asyncio
import subprocess
import sys
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

class ReloadHandler(FileSystemEventHandler):
    def on_modified(self, event):
        if event.src_path.endswith('.py'):
            print(f"🔁 Изменение в {event.src_path}, перезапускаю...")
            observer.stop()
            subprocess.run([sys.executable, 'main.py'])

if __name__ == "__main__":
    observer = Observer()
    observer.schedule(ReloadHandler(), path='.', recursive=True)
    observer.start()
    print("👀 Слежу за изменениями...")
    try:
        while True:
            asyncio.run(asyncio.sleep(1))
    except KeyboardInterrupt:
        observer.stop()
    observer.join()