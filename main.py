import shutil
import webbrowser
import yaml
from flask import Flask, request, jsonify, render_template
import os
import cv2
import numpy as np
import base64
import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service as ChromeService
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup
import io
from threading import Thread, Timer
from PIL import Image
import random
from time import sleep

app = Flask(__name__)

UPLOAD_FOLDER = 'uploads'
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

pech = 0
pechmax = 0
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
    global pech
    data = request.json

    pech = 0
    Thread(target=data_gen, args=(data,)).start()

    return jsonify(['ok'])


@app.route('/getp')
def getp():
    global pech, pechmax
    return jsonify({'pech': pech,
                    'pechmax': pechmax})


def data_gen(data):
    global pech, pechmax
    ngen = int(data['togen'])
    data = data['data']

    try:
        os.mkdir('./data')
        os.mkdir('./data/images')
        os.mkdir('./data/labels')
    except:
        pass
    for folder in ["./data/images", "./data/labels"]:
        for filename in os.listdir(folder):
            file_path = os.path.join(folder, filename)
            try:
                if os.path.isfile(file_path) or os.path.islink(file_path):
                    os.unlink(file_path)
                elif os.path.isdir(file_path):
                    shutil.rmtree(file_path)
            except Exception as e:
                print('Failed to delete %s. Reason: %s' % (file_path, e))
    with open("./data/data.yaml", "w") as file:
        yaml.dump({
            'nc': len(data),
            'names': [cls['name'] for cls in data]
        }, file)

    img_count = 0
    to_choice = 0

    options = Options()
    # options.add_argument(
    #     "user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/51.0.2704.103 Safari/537.36")
    options.headless = True
    options.add_argument("--headless")
    driver = webdriver.Chrome(service=ChromeService(ChromeDriverManager().install()), options=options)
    driver.get(f'https://yandex.ru/images/search?text=фон')

    for i in range(10):
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        sleep(1)

    soup = BeautifulSoup(driver.page_source)

    imgs_block = soup.find_all('img', class_='ContentImage-Image')

    pechmax = sum(ngen - ngen % len(cls['files']) for cls in data)

    for cls_id, cls in enumerate(data):
        # name = cls['name']
        simgs = len(cls['files'])

        for bimg in cls['files']:
            image_data = bimg.split('base64,')[1]
            imgdata = base64.b64decode(image_data)
            # np_array = np.frombuffer(io.BytesIO(imgdata).getvalue(), dtype=np.uint8)
            # img = cv2.imdecode(np_array, cv2.IMREAD_COLOR)
            # color_converted = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            # pil_image = Image.fromarray(color_converted).convert("RGBA")
            pil_image = Image.open(io.BytesIO(imgdata)).convert("RGBA")

            n_img = pil_image.resize((150, int(pil_image.height * (150 / pil_image.width))))

            for i in range(ngen // simgs):
                no_img = True
                while no_img:
                    try:
                        img_url = f"https:{imgs_block[to_choice]['src']}"

                        response = requests.get(img_url)
                        img = Image.open(io.BytesIO(response.content))
                        size = min(img.size)
                        img = img.crop((0, 0, size, size)).resize((416, 416))
                        size = 416
                        no_img = False
                    except IndexError:
                        to_choice = 0
                        driver.get(f'https://yandex.ru/images/search?text={random.choice(to_find)}')
                        for i in range(10):
                            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                            sleep(1)

                        soup = BeautifulSoup(driver.page_source)

                        imgs_block = soup.find_all('img', class_='ContentImage-Image')

                    except:
                        return
                    to_choice += 1

                res = random.randint(1, 4)
                pos = (random.randint(0, size - n_img.width // res),
                       random.randint(0, size - n_img.height // res))

                img.paste(n_img.resize((n_img.width // res, n_img.height // res)),
                          pos, n_img.resize((n_img.width // res, n_img.height // res)))

                # cx = n_img.width // 2 / res
                # cy = n_img.height // 2 / res

                bx, by = pos[0], pos[1]
                bw = n_img.width / res
                bh = n_img.height / res

                bx += bw / 2
                by += bh / 2

                bbox = (bx / 416, by / 416, bw / 416, bh / 416)

                img.save(f'./data/images/{img_count}.png')
                with open(f'./data/labels/{img_count}.txt', 'w') as labelf:
                    labelf.write('{} {} {} {} {}'.format(cls_id, *bbox))

                img_count += 1

                pech += 1

    pech = -1
    driver.close()


def open_browser():
    webbrowser.open_new("http://localhost:1488")


if __name__ == '__main__':
    Timer(2, open_browser).start()
    app.run(port=1488)
