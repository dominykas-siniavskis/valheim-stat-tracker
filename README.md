# Valheim Stat Tracker

## What to do
- Install Java 17 from here: https://download.oracle.com/java/17/archive/jdk-17.0.12_windows-x64_bin.msi
- Install Python 3.13
- Download valheim-save-tools from here: https://github.com/Kakoen/valheim-save-tools/releases/download/1.1.3/valheim-save-tools.jar
- Download this project. Via Git or just .zip. Save in an easy to access directory. Like `C:\User\Documents`
- Drop the save tools in the `app/` directory of local project
- Create a .env file, fill it out.
- Install gitbash cause I don't know how powershell works (Or not)
    - Go to the directory in which the project was unpacked.
    - in gitbash `source venv/Scripts/activate`
- Alternatively in powershell:
    - Go to the directory in which the project was unpacked.
    - in powershell CD to the venv/Scripts and just run `.\activate`
    - CD out of script directory into `valheim-lan-integration`
- run `py -m pip install -r requirements.txt`
- run `py app/main.py`