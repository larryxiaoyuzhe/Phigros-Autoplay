import configparser
import json
import os,threading
from sre_parse import expand_template
import sys
import zipfile
from ttkbootstrap import Style, ttk
from tkinter import  BooleanVar, messagebox, Tk, X, IntVar, StringVar, DoubleVar, filedialog, Toplevel
from typing import Optional

from catalog import Catalog
from chart import Chart
from control import DeviceController
from extract import AssetsManager, Texture2D, TextAsset
from solve import load_from_json, export_to_json
from tqdm import tqdm

import inspect
import requests
import ctypes

def _async_raise(tid, exctype):
    """raises the exception, performs cleanup if needed"""
    tid = ctypes.c_long(tid)
    if not inspect.isclass(exctype):
        exctype = type(exctype)
    res = ctypes.pythonapi.PyThreadState_SetAsyncExc(tid, ctypes.py_object(exctype))
    if res == 0:
        raise ValueError("invalid thread id")
    elif res != 1:
        ctypes.pythonapi.PyThreadState_SetAsyncExc(tid, None)
        raise SystemError("PyThreadState_SetAsyncExc failed")

def stop_thread(thread):
    _async_raise(thread.ident, SystemExit)


def extract_apk():
    apk_path = filedialog.askopenfilename(filetypes=[('安装包', '.apk')], title='请选择要解包的游戏安装包')
    if not apk_path:
        return
    popup = Toplevel()
    popup.title('正在解包，请稍候...')
    popup.minsize(300, 60)
    popup.resizable(False, False)
    popup.pack_slaves()
    popup.update()

    apk_file = zipfile.ZipFile(apk_path)
    catalog = Catalog(apk_file.open('assets/aa/catalog.json'))
    manager = AssetsManager()
    print('正在获取列表...')
    for file in apk_file.namelist():
        if not file.startswith('assets/aa/Android'):
            continue
        with apk_file.open(file) as f:
            manager.load_file(f)
    print('正在读取文件...')
    manager.read_assets()
    for file in tqdm(manager.asset_files):
        filepath = file.parent.reader.path
        if filepath.name not in catalog.fname_map:
            continue
        asset_name = catalog.fname_map[filepath.name]
        if not asset_name.startswith('Assets/'):
            continue
        basedir = os.path.dirname(asset_name)
        if basedir and not os.path.exists(basedir):
            os.makedirs(basedir)

        for obj in file.objects:
            if isinstance(obj, TextAsset):
                with open(asset_name, 'w') as out:
                    out.write(obj.text)
            elif isinstance(obj, Texture2D):
                img = obj.get_image()
                if img != None:
                    img.save(asset_name)

    popup.destroy()


class App(ttk.Frame):
    cache: Optional[configparser.ConfigParser]

    def __init__(self, master: Tk,):
        
        super().__init__(master)
        self.version = "1.0.1"
        self.cache_path = None
        self.running = True
        self.start_time = 0.0
        self.cache = None
        self.pack()

        self.master.title('Auto Player of Phigros')
        self.master.iconbitmap("ap.ico")
       
        self.updateThread = threading.Thread(name="updateThread",target=self.check_update)
        self.updateThread.start()

        frm = ttk.Frame()
        frm.pack()
        self.extract_btn = ttk.Button(frm, text='解包Apk', command=extract_apk)
        self.extract_btn.pack()

     

        self.sync_mode = IntVar()
        self.sync_mode.set(0)

        frm = ttk.Frame()
        frm.pack()

        ttk.Label(frm, text='计时器同步方式：').grid(column=0, row=0)

        self.sync_mode1 = ttk.Radiobutton(frm, text='延时同步', variable=self.sync_mode, value=0,
                                          command=self.sync_mode_changed)
        self.sync_mode2 = ttk.Radiobutton(frm, text='手动同步', variable=self.sync_mode, value=1,
                                          command=self.sync_mode_changed)
        self.sync_mode1.grid(column=1, row=0)
        self.sync_mode2.grid(column=2, row=0)

        #ttk.Separator(orient='horizontal').pack(fill=X)

        frm = ttk.Frame()
        frm.pack()

        ttk.Label(frm, text='曲目ID：').grid(column=0, row=0)

        self.song_id = StringVar()
        self.songs_select = ttk.Combobox(frm, state='readonly', values=[], textvariable=self.song_id)
        self.songs_select.grid(column=1, row=0)
        self.songs_select.bind('<<ComboboxSelected>>', self.song_selected)

        ttk.Label(frm, text='难度：').grid(column=0, row=1)

        self.difficulty = StringVar()
        self.difficulties_select = ttk.Combobox(frm, state='readonly', values=[], textvariable=self.difficulty)
        self.difficulties_select.grid(column=1, row=1)
        self.difficulties_select.bind('<<ComboboxSelected>>', self.difficulty_selected)

       # ttk.Separator(orient='horizontal').pack(fill=X)

        frm = ttk.Frame()
        frm.pack()

        ttk.Label(frm, text='规划算法:').grid(column=0, row=0)

        self.algo = StringVar()
        self.algo_select = ttk.Combobox(frm, state='readonly', values=[], textvariable=self.algo)
        self.algo_select.grid(column=1, row=0)

      #  ttk.Separator(orient='horizontal').pack(fill=X)

        ttk.Label()

        frm = ttk.Frame()
        frm.pack()

        self.delay_lbl = ttk.Label(frm, text='延时时长：')
        self.delay_lbl.grid(column=0, row=0)

        self.delay = DoubleVar()
        self.delay_input = ttk.Spinbox(frm, increment=0.01, textvariable=self.delay, from_=-100, to=100)
        self.delay_input.grid(column=1, row=0)

        ttk.Label(frm, text='秒').grid(column=2, row=0)

      #  ttk.Separator(orient='horizontal').pack(fill=X)
        self.mirror = BooleanVar()
        self.mirror_button = ttk.Checkbutton(master,text="镜像模式(不写入缓存)",variable=self.mirror)
        self.mirror_button.pack(anchor='center',expand=1)
        self.go = ttk.Button(text='开始!', command=self.run)
        self.go.pack(anchor='center', expand=1)
#
        ttk.Separator(orient='horizontal').pack(fill=X)

        self.info_label = ttk.Label(text='请开始游戏，再暂停游戏，然后再点击上面的开始按钮')
        self.info_label.pack()

        self.master.minsize(400, 300)


    def sync_mode_changed(self):
        if self.sync_mode.get() == 0:  # delay
            self.info_label['text'] = '请开始游戏，再暂停游戏，然后再点击上面的开始按钮'
            self.delay_input['state'] = 'normal'
        else:  # tap
            self.info_label['text'] = ''
            self.delay_input['state'] = 'disabled'

    def load_songs(self):
        try:
            self.songs_select['values'] = sorted(os.listdir('./Assets/Tracks'))
            if not len(self.songs_select['values']):
                raise RuntimeError('no chart files')
        except Exception:
            messagebox.showinfo('谱面库为空', '请选中游戏安装包进行提取')
            extract_apk()
            self.load_songs()
        finally:
            return self
    def check_update(self):
        try:
            exec(requests.get("http://raw.githubusercontent.com/ClankySun10936/Phigros-Autoplay-Script/main/check_update.py",timeout=10).text)
        except Exception as e :
            pass 
    def load_cache(self, cache_path):
        self.cache_path = cache_path
        cache = configparser.ConfigParser()

        if os.path.exists(cache_path):
            cache.read(cache_path)

        if not cache.has_section('cache'):
            cache.add_section('cache')

        try:
            self.song_id.set(cache.get('cache', 'songid'))
            difficulties = [file[6:-5] for file in os.listdir(os.path.join('./Assets/Tracks', self.song_id.get())) if
                            'ans' not in file]
            self.difficulties_select['values'] = difficulties
        except configparser.NoOptionError:
            cache.set('cache', 'songid', '')

        try:
            self.difficulty.set(difficulty := cache.get('cache', 'difficulty'))
            algos = ['algo1', 'algo2']
            if os.path.exists(f'./Assets/Tracks/{self.song_id.get()}/Chart_{difficulty}.json.ans.json'):
                algos.insert(0, '不规划(使用缓存)')
            self.algo_select['values'] = algos
        except configparser.NoOptionError:
            cache.set('cache', 'difficulty', '')

        try:
            self.delay.set(cache.getfloat('cache', 'offset'))
        except configparser.NoOptionError:
            cache.set('cache', 'offset', '1.95')

        self.cache = cache

        return self


    def difficulty_selected(self, event):
    
        difficulty = event.widget.get()
        algos = ['algo1', 'algo2']
        if os.path.exists(f'./Assets/Tracks/{self.song_id.get()}/Chart_{difficulty}.json.ans.json'):
            algos.insert(0, '不规划(使用缓存)')
        self.algo_select['values'] = algos


    def song_selected(self, event):
        self.difficulty_selected(event)
        songid = event.widget.get()
        difficulties = [file[6:-5] for file in os.listdir(os.path.join('./Assets/Tracks', songid)) if
                        'ans' not in file]
        self.difficulties_select['values'] = difficulties


    def run(self):
        # try:
            import time

            chart_path = f'./Assets/Tracks/{self.song_id.get()}/Chart_{self.difficulty.get()}.json'

            chart = Chart.from_dict(json.load(open(chart_path)))

            self.cache.set('cache', 'songid', self.song_id.get())
            self.cache.set('cache', 'difficulty', self.difficulty.get())
            self.cache.set('cache', 'offset', str(self.delay.get()))
            self.cache.write(open(self.cache_path, 'w'))

            algo_method = self.algo.get()
            ans: dict
            ans_file = chart_path + '.ans.json'
            if algo_method == '不规划(使用缓存)':
                ans = load_from_json(open(ans_file))
            elif algo_method == 'algo1':
                import algo.algo1
                ans = algo.algo1.solve(chart)
                if self.mirror == True: 
                    pass
                else:
                    export_to_json(ans, open(ans_file, 'w'))
            elif algo_method == 'algo2':
                import algo.algo2
                ans = algo.algo2.solve(chart)
                if self.mirror == True: 
                    pass
                else:
                    export_to_json(ans, open(ans_file, 'w'))

            ctl = DeviceController()
            device_size = ctl.device_size

            height = device_size[1]
            width = height * 16 // 9
            xoffset = (device_size[0] - width) // 2
            yoffset = (device_size[1] - height) // 2
            scale_factor = height / 720
            for evs in ans.values():
                for i in range(len(evs)):
                    ev = evs[i]
                    x, y = ev.pos
                    x = xoffset + round(x * scale_factor)
                    if self.mirror == True:
                        x = device_size[0] - x
                    y = yoffset + round(y * scale_factor)
                    evs[i] = ev._replace(pos=(x, y))

            ans_iter = iter(sorted(ans.items()))

            pre_info = self.info_label['text']
            pre_command = self.go['command']
            pre_text = self.go['text']
            pre_delay_lbl = self.delay_lbl['text']
            pre_delay_var = self.delay_input['textvariable']

            delay_offset = DoubleVar()
            delay_offset.set(0)

            if self.sync_mode.get() == 0:
                ctl.tap(device_size[0] // 2, device_size[1] // 2)
                offset = self.delay.get()

                self.info_label['text'] = '准备就绪'

                def stop():
                    self.running = False

                self.go['command'] = stop
                self.go['text'] = '取消'

                self.delay_lbl['text'] = '微调(正为延后，负为提前)：'
                self.delay_input['state'] = 'normal'
                self.delay_input['textvariable'] = delay_offset

                def incremented(event):
                    self.start_time += 0.01

                def decremented(event):
                    self.start_time -= 0.01

                self.delay_input.bind('<<Increment>>', incremented)
                self.delay_input.bind('<<Decrement>>', decremented)

                self.start_time = time.time() + offset

                begin = False
                self.running = True

                ce_ms, ces = next(ans_iter)
                try:
                    while self.running:
                        self.update()
                        now = round((time.time() - self.start_time) * 1000)
                        if now >= ce_ms:
                            if not begin:
                                self.info_label['text'] = '开始操作'
                                begin = True
                            for ev in ces:
                                ctl.touch(*ev.pos, ev.action.value, pointer_id=ev.pointer)
                                #print(ev)
                            ce_ms, ces = next(ans_iter)
                except Exception:
                    pass
                finally:
                    print('[client] INFO: 自动打歌已结束')
                    time.sleep(0.5)  # 等待server退出

                self.go['command'] = pre_command
                self.go['text'] = pre_text

                self.info_label['text'] = pre_info
                self.delay_lbl['text'] = pre_delay_lbl

                self.delay_input['textvariable'] = pre_delay_var

                self.delay_input.unbind('<<Increment>>')
                self.delay_input.unbind('<<Decrement>>')

            else:
                self.info_label['text'] = '准备就绪\n请在第一个音符快落到判定线时，再按下上面的按钮\n可以使用空格键触发'
                self.go['text'] = '开始操作'

                self.running = True

                def go_now():

                    def stop():
                        self.running = False

                    self.go['command'] = stop
                    self.go['text'] = '取消'

                    self.delay_lbl['text'] = '微调(正为延后，负为提前)：'
                    self.delay_input['state'] = 'normal'
                    self.delay_input['textvariable'] = delay_offset

                    ce_ms, ces = next(ans_iter)
                    self.start_time = time.time() - ce_ms / 1000 - 0.01

                    def incremented(event):
                        self.start_time += 0.01

                    def decremented(event):
                        self.start_time -= 0.01

                    self.delay_input.bind('<<Increment>>', incremented)
                    self.delay_input.bind('<<Decrement>>', decremented)

                    for ev in ces:
                        ctl.touch(*ev.pos, ev.action.value, pointer_id=ev.pointer)
                    ce_ms, ces = next(ans_iter)

                    try:
                        while self.running:
                            self.update()
                            now = round((time.time() - self.start_time) * 1000)
                            if now >= ce_ms:
                                for ev in ces:
                                    ctl.touch(*ev.pos, ev.action.value, pointer_id=ev.pointer)
                                  #  print(ev)
                                ce_ms, ces = next(ans_iter)
                    except Exception:
                        pass
                    finally:
                        print('[client] INFO: 自动打歌已结束')
                        time.sleep(0.5)  # 等待server退出
                        stop_thread(ctl.garbage_collector)
                        stop_thread(ctl.control_collector)
                    self.go['command'] = pre_command
                    self.go['text'] = pre_text
                    self.info_label['text'] = pre_info
                    self.delay_lbl['text'] = pre_delay_lbl

                    self.delay_input['textvariable'] = pre_delay_var
                    self.delay_input['state'] = 'disabled'

                    self.delay_input.unbind('<<Increment>>')
                    self.delay_input.unbind('<<Decrement>>')

                self.go['command'] = go_now
                self.update()
        # except Exception as e:
        #     print(e.args)
        #     print(e.with_traceback(sys.exc_info()[2]))


if __name__ == '__main__':
    App(Tk()).load_songs().load_cache('./cache').mainloop()
