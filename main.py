import shutil
import webbrowser
import yaml
from flask import Flask, request, jsonify, render_template
import base64
import binascii
import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service as ChromeService
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup
import io
from threading import Lock, Thread, Timer
from pathlib import Path
from urllib.parse import urljoin
from PIL import Image
import random
from time import sleep

app = Flask(__name__)

DATA_FOLDER = Path(__file__).resolve().parent / 'data'
pech = 0
pechmax = 0
progress_error = None
job_lock = Lock()
progress_lock = Lock()
to_find = (
    'фон',
    'backgroung',
    'forest',
    'лес',
    'природа',
    'color',
    'ground',
    'fon',
    'задний фон',
    'катинка',
    'абстракция'
)


@app.route("/")
def index():
    return render_template('index.html')


@app.route('/upload_cards', methods=['POST'])
def upload_cards():
    global pech, pechmax, progress_error
    try:
        data = validate_data(request.get_json(silent=True))
    except ValueError as error:
        return jsonify({'error': str(error)}), 400
    if not job_lock.acquire(blocking=False):
        return jsonify({'error': 'Генерация уже выполняется. Дождитесь завершения.'}), 409
    with progress_lock:
        pech = 0
        pechmax = data['togen'] * len(data['data'])
        progress_error = None
    try:
        Thread(target=run_generation, args=(data,), daemon=True).start()
    except RuntimeError:
        with progress_lock:
            pech = -2
            progress_error = 'Не удалось запустить задачу генерации.'
            error = progress_error
        job_lock.release()
        return jsonify({'error': error}), 500
    return jsonify(['ok'])


@app.route('/getp')
def getp():
    with progress_lock:
        return jsonify({'pech': pech, 'pechmax': pechmax, 'error': progress_error})


def decode_image(value):
    if not isinstance(value, str):
        raise ValueError('Изображение должно быть передано как data URL.')
    header, separator, encoded = value.partition(',')
    if not separator or not header.startswith('data:image/') or not header.endswith(';base64'):
        raise ValueError('Некорректный формат изображения: ожидается base64 data URL.')
    try:
        raw = base64.b64decode(encoded, validate=True)
        with Image.open(io.BytesIO(raw)) as image:
            return image.convert('RGBA')
    except (ValueError, binascii.Error, OSError, Image.DecompressionBombError) as error:
        raise ValueError('Не удалось прочитать изображение.') from error


def validate_data(data):
    if not isinstance(data, dict):
        raise ValueError('Ожидается JSON-объект с классами и количеством изображений.')
    count = data.get('togen')
    if isinstance(count, bool) or not isinstance(count, (int, str)):
        raise ValueError('Количество изображений должно быть положительным целым числом.')
    try:
        count = int(count)
    except ValueError as error:
        raise ValueError('Количество изображений должно быть положительным целым числом.') from error
    if count <= 0:
        raise ValueError('Количество изображений должно быть больше нуля.')
    classes = data.get('data')
    if not isinstance(classes, list) or not classes:
        raise ValueError('Добавьте хотя бы один класс с изображениями.')
    names = set()
    for cls in classes:
        if not isinstance(cls, dict) or not isinstance(cls.get('name'), str) or not cls['name'].strip():
            raise ValueError('У каждого класса должно быть непустое название.')
        name = cls['name'].strip()
        if name in names:
            raise ValueError('Названия классов должны быть уникальными.')
        names.add(name)
        if not isinstance(cls.get('files'), list) or not cls['files']:
            raise ValueError('Добавьте хотя бы одно изображение в каждый класс.')
        for value in cls['files']:
            decode_image(value).close()
    return {'togen': count, 'data': classes}


def run_generation(data):
    global pech, progress_error
    try:
        data_gen(data)
        with progress_lock:
            pech = -1
    except Exception:
        app.logger.exception('Dataset generation failed')
        with progress_lock:
            pech = -2
            progress_error = 'Генерация прервана. Проверьте Chrome, интернет и журнал сервера.'
    finally:
        job_lock.release()


def find_backgrounds(driver, query):
    driver.get('https://yandex.ru/images/search?text=' + query)
    for _ in range(10):
        driver.execute_script('window.scrollTo(0, document.body.scrollHeight);')
        sleep(1)
    soup = BeautifulSoup(driver.page_source, 'html.parser')
    return [urljoin('https://yandex.ru', image['src'])
            for image in soup.select('img.ImagesContentImage-Image, img.ContentImage-Image')
            if image.get('src')]


def data_gen(data):
    global pech
    ngen = data['togen']
    classes = data['data']
    driver = None
    options = Options()
    options.add_argument("--headless")
    try:
        driver = webdriver.Chrome(service=ChromeService(ChromeDriverManager().install()), options=options)
        driver.set_page_load_timeout(30)
        backgrounds = find_backgrounds(driver, 'фон')
        if not backgrounds:
            raise RuntimeError('Поиск не вернул фоновые изображения.')
        for folder in (DATA_FOLDER / 'images', DATA_FOLDER / 'labels'):
            folder.mkdir(parents=True, exist_ok=True)
            for path in folder.iterdir():
                if path.is_symlink() or path.is_file():
                    path.unlink()
                elif path.is_dir():
                    shutil.rmtree(path)
        with (DATA_FOLDER / 'data.yaml').open('w', encoding='utf-8') as file:
            yaml.safe_dump({'nc': len(classes), 'names': [cls['name'] for cls in classes]},
                           file, allow_unicode=True)

        img_count = 0
        to_choice = 0
        for cls_id, cls in enumerate(classes):
            for file_id, value in enumerate(cls['files']):
                # Distribute the remainder so the requested count is exact, even for small jobs.
                repeats = ngen // len(cls['files']) + (file_id < ngen % len(cls['files']))
                if not repeats:
                    continue
                with decode_image(value) as source:
                    n_img = source.copy()
                n_img.thumbnail((150, 416))
                for _ in range(repeats):
                    img = None
                    for _attempt in range(30):
                        if to_choice >= len(backgrounds):
                            backgrounds = find_backgrounds(driver, random.choice(to_find))
                            to_choice = 0
                        if not backgrounds:
                            raise RuntimeError('Поиск не вернул фоновые изображения.')
                        img_url = backgrounds[to_choice]
                        to_choice += 1
                        try:
                            with requests.get(img_url, timeout=(5, 20)) as response:
                                response.raise_for_status()
                                with Image.open(io.BytesIO(response.content)) as background:
                                    size = min(background.size)
                                    img = background.crop((0, 0, size, size)).resize((416, 416)).convert('RGB')
                            break
                        except (requests.RequestException, OSError, Image.DecompressionBombError):
                            continue
                    if img is None:
                        raise RuntimeError('Не удалось загрузить фон после 30 попыток.')
                    res = random.randint(1, 4)
                    width = max(1, n_img.width // res)
                    height = max(1, n_img.height // res)
                    pos = (random.randint(0, 416 - width), random.randint(0, 416 - height))
                    with n_img.resize((width, height)) as foreground:
                        img.paste(foreground, pos, foreground)
                    bbox = ((pos[0] + width / 2) / 416, (pos[1] + height / 2) / 416,
                            width / 416, height / 416)
                    img.save(DATA_FOLDER / 'images' / f'{img_count}.png')
                    img.close()
                    with (DATA_FOLDER / 'labels' / f'{img_count}.txt').open('w', encoding='utf-8') as file:
                        file.write('{} {} {} {} {}'.format(cls_id, *bbox))
                    img_count += 1
                    with progress_lock:
                        pech += 1
                n_img.close()
    finally:
        if driver is not None:
            driver.quit()


def open_browser():
    webbrowser.open_new("http://localhost:1488")


if __name__ == '__main__':
    Timer(2, open_browser).start()
    app.run(port=1488)
