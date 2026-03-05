# tosun-geehy-can-uds-tools

Объединённый графический инструмент для работы с CAN/UDS устройствами Geehy APM32.

Проект собирает в одном приложении четыре сценария:
- программирование через bootloader;
- калибровка датчика;
- сбор данных в CSV и графический анализ;
- чтение и запись UDS DID-параметров.

## Что находится на главном экране
- подключение к CAN-адаптеру TSCAN;
- запуск и остановка трассировки CAN;
- общие параметры протокола и Source Address;
- ручная настройка UDS CAN идентификаторов;
- автоопределение адресов по входящему J1939-потоку;
- панель запуска специализированных окон;
- краткая сводка по текущему состоянию всех сценариев.

## Какие окна открываются отдельно
- `Программирование` — загрузка BIN и запуск bootloader-сценария;
- `Калибровка` — пошаговая запись 0%/100%, автопроверка, backup/restore;
- `Коллектор и анализ` — опрос узлов, CSV, тренды и сетевые метрики;
- `Параметры UDS` — одиночные DID-операции и массовое чтение DID.

Все специализированные окна немодальные и могут открываться из главной панели.

## Требования
- Windows 10/11 x64;
- Python 3.13+;
- CAN-адаптер TSCAN и библиотеки `libTSCANAPI`;
- зависимости из `requirements.txt`.

## Запуск из исходников
```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

## Сборка через PyInstaller
```powershell
.\.venv\Scripts\pyinstaller.exe --clean --noconfirm main.spec
```

Результат сборки:
- каталог `dist/tosun-geehy-can-uds-tools/`
- исполняемый файл `dist/tosun-geehy-can-uds-tools/tosun-geehy-can-uds-tools.exe`

## Архитектура
- `main.py` — точка входа;
- `ui/qml/Main.qml` — композиция главного экрана и окон инструментов;
- `ui/qml/components/*.qml` — переиспользуемые UI-модули;
- `ui/qml/app_controller.py` — корневой контроллер;
- `ui/qml/controller/*_mixin.py` — разнесённая логика по подсистемам;
- `ui/qml/collector_csv_manager.py` — работа с CSV для коллектора;
- `app_can/CanDevice.py` — транспорт CAN через `libTSCANAPI`;
- `uds/services/*` — UDS сервисы.
