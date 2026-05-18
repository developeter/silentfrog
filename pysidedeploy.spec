[app]
title = Silentfrog
project_dir = .
input_file = deploy/main.py
project_file =
exec_directory = .
icon = src/silentfrog/assets/icon.png

[python]
python_path = python3
packages = Nuitka==2.7.11

[qt]
qml_files =
excluded_qml_plugins =
modules =
plugins =

[android]
wheel_pyside =
wheel_shiboken =
plugins =

[nuitka]
macos.permissions =
mode = standalone
macos_create_app_bundle = True
# extra_args is appended to nuitka. Exclusions here work around a Nuitka 2.7.11
# assertion ("Must not attempt to locate <ModuleName 'pyRdfa'>") triggered by the
# RDFa parsers pulled in transitively through extruct.
extra_args = --quiet --noinclude-qt-translations --nofollow-import-to=pyRdfa --nofollow-import-to=pyMicrodata --nofollow-import-to=rdflib

[buildozer]
