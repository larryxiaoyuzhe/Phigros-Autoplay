import zipfile
from tkinter import filedialog

apk_path = filedialog.askopenfilename(filetypes=[('安装包', '.apk')], title='请选择要解包的游戏安装包')
apk_file = zipfile.ZipFile(apk_path)
print(apk_file.namelist())
apk_file.close()