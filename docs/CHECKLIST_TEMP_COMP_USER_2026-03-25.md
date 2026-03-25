# Чек-лист восстановления требований (25.03.2026)

Статусы:
- `[ ]` не выполнено
- `[~]` в работе / частично
- `[x]` выполнено

## Список задач
- [x] 1) При загрузке нового CSV в разделе температурной компенсации пересчитывать данные и итог оффлайн-анализа.
Что сделано: загрузка CSV/XLSX запускает пересчет и обновление статуса/метрик.
Ссылки: [public_slots_mixin.py#L1092](/d:/revkovms/dev/_GUIs/tosun-geehy-can-uds-tools-git/ui/qml/controller/public_slots_mixin.py#L1092), [public_slots_mixin.py#L1128](/d:/revkovms/dev/_GUIs/tosun-geehy-can-uds-tools-git/ui/qml/controller/public_slots_mixin.py#L1128), [calibration_mixin.py#L1943](/d:/revkovms/dev/_GUIs/tosun-geehy-can-uds-tools-git/ui/qml/controller/calibration_mixin.py#L1943).

- [x] 2) Для `all_nodes.csv` не обновлять верхний селектор CAN-узла; добавить отдельный селектор набора данных внутри блока температурной компенсации.
Что сделано: добавлен отдельный селектор набора CSV/XLSX внутри temp-comp и логика переключения набора; выбор CAN-узла сверху остается отдельным.
Ссылки: [CalibrationCard.qml#L785](/d:/revkovms/dev/_GUIs/tosun-geehy-can-uds-tools-git/ui/qml/components/CalibrationCard.qml#L785), [CalibrationCard.qml#L804](/d:/revkovms/dev/_GUIs/tosun-geehy-can-uds-tools-git/ui/qml/components/CalibrationCard.qml#L804), [public_slots_mixin.py#L253](/d:/revkovms/dev/_GUIs/tosun-geehy-can-uds-tools-git/ui/qml/controller/public_slots_mixin.py#L253), [calibration_mixin.py#L2781](/d:/revkovms/dev/_GUIs/tosun-geehy-can-uds-tools-git/ui/qml/controller/calibration_mixin.py#L2781).

- [x] 3) Убрать сильные лаги/тормоза при нажатии кнопки «Прочитать из МК».
Что сделано: чтение DID переведено в последовательную очередь с таймаутом/задержкой и прогрессом; перерисовка графика дебаунсится.
Ссылки: [public_slots_mixin.py#L550](/d:/revkovms/dev/_GUIs/tosun-geehy-can-uds-tools-git/ui/qml/controller/public_slots_mixin.py#L550), [calibration_mixin.py#L3258](/d:/revkovms/dev/_GUIs/tosun-geehy-can-uds-tools-git/ui/qml/controller/calibration_mixin.py#L3258), [TrendCanvas.qml#L226](/d:/revkovms/dev/_GUIs/tosun-geehy-can-uds-tools-git/ui/qml/components/TrendCanvas.qml#L226), [TrendCanvas.qml#L822](/d:/revkovms/dev/_GUIs/tosun-geehy-can-uds-tools-git/ui/qml/components/TrendCanvas.qml#L822).

- [x] 4) Читать из МК только параметры, относящиеся к выбранному режиму компенсации.
Что сделано: `Чтение из текущего режима` отправляет mode-aware очередь DID + K1/K0.
Ссылки: [CalibrationCard.qml#L847](/d:/revkovms/dev/_GUIs/tosun-geehy-can-uds-tools-git/ui/qml/components/CalibrationCard.qml#L847), [public_slots_mixin.py#L550](/d:/revkovms/dev/_GUIs/tosun-geehy-can-uds-tools-git/ui/qml/controller/public_slots_mixin.py#L550), [public_slots_mixin.py#L584](/d:/revkovms/dev/_GUIs/tosun-geehy-can-uds-tools-git/ui/qml/controller/public_slots_mixin.py#L584), [calibration_mixin.py#L3353](/d:/revkovms/dev/_GUIs/tosun-geehy-can-uds-tools-git/ui/qml/controller/calibration_mixin.py#L3353).

- [x] 5) Вынести калибровку 0% и 100% в отдельный спойлер.
Что сделано: выделен отдельный спойлер калибровки уровней.
Ссылки: [CalibrationCard.qml#L402](/d:/revkovms/dev/_GUIs/tosun-geehy-can-uds-tools-git/ui/qml/components/CalibrationCard.qml#L402).

- [x] 6) Привести цвета кнопок к спокойной схеме без градиентов, с понятной семантикой.
Что сделано: кнопки работают на плоской цветовой схеме (без градиентов), цвета разведены по смыслу действий.
Ссылки: [FancyButton.qml#L37](/d:/revkovms/dev/_GUIs/tosun-geehy-can-uds-tools-git/ui/qml/components/FancyButton.qml#L37), [CalibrationCard.qml#L825](/d:/revkovms/dev/_GUIs/tosun-geehy-can-uds-tools-git/ui/qml/components/CalibrationCard.qml#L825), [CalibrationCard.qml#L874](/d:/revkovms/dev/_GUIs/tosun-geehy-can-uds-tools-git/ui/qml/components/CalibrationCard.qml#L874).

- [x] 7) Минимизировать блок «Итог офлайн-анализа»: убрать/заменить большой текстовый блок на компактные метрики.
Что сделано: блок оставлен в виде компактного спойлера с метриками и кратким статусом.
Ссылки: [CalibrationCard.qml#L965](/d:/revkovms/dev/_GUIs/tosun-geehy-can-uds-tools-git/ui/qml/components/CalibrationCard.qml#L965).

- [x] 8) Убрать «Быстрое превью линейного режима» в отдельный спойлер (по умолчанию закрыт); поправить высоту полей K0/K1.
Что сделано: превью вынесено в отдельный закрытый спойлер, поля K0/K1 увеличены по высоте.
Ссылки: [CalibrationCard.qml#L1657](/d:/revkovms/dev/_GUIs/tosun-geehy-can-uds-tools-git/ui/qml/components/CalibrationCard.qml#L1657), [CalibrationCard.qml#L1727](/d:/revkovms/dev/_GUIs/tosun-geehy-can-uds-tools-git/ui/qml/components/CalibrationCard.qml#L1727), [CalibrationCard.qml#L1747](/d:/revkovms/dev/_GUIs/tosun-geehy-can-uds-tools-git/ui/qml/components/CalibrationCard.qml#L1747).

- [x] 9) Визуально разделить секции блока температурной компенсации, чтобы элементы не сливались.
Что сделано: секции разделены отдельными карточками/спойлерами с разными фонами и рамками.
Ссылки: [CalibrationCard.qml#L693](/d:/revkovms/dev/_GUIs/tosun-geehy-can-uds-tools-git/ui/qml/components/CalibrationCard.qml#L693), [CalibrationCard.qml#L965](/d:/revkovms/dev/_GUIs/tosun-geehy-can-uds-tools-git/ui/qml/components/CalibrationCard.qml#L965), [CalibrationCard.qml#L1160](/d:/revkovms/dev/_GUIs/tosun-geehy-can-uds-tools-git/ui/qml/components/CalibrationCard.qml#L1160), [CalibrationCard.qml#L1657](/d:/revkovms/dev/_GUIs/tosun-geehy-can-uds-tools-git/ui/qml/components/CalibrationCard.qml#L1657).

- [~] 10) Разобрать и устранить сценарий: после записи линейных коэффициентов на МК на комнатной температуре отклонение > 18%.
Что сделано: добавлена понятная операторская методика причин/действий и автоматическая кнопка подгонки K0; требуется стенд-подтверждение «до/после» на реальном узле.
Ссылки: [TEMP_COMP_K0_WORKFLOW.md#L1](/d:/revkovms/dev/_GUIs/tosun-geehy-can-uds-tools-git/docs/TEMP_COMP_K0_WORKFLOW.md#L1), [CalibrationCard.qml#L874](/d:/revkovms/dev/_GUIs/tosun-geehy-can-uds-tools-git/ui/qml/components/CalibrationCard.qml#L874), [public_slots_mixin.py#L494](/d:/revkovms/dev/_GUIs/tosun-geehy-can-uds-tools-git/ui/qml/controller/public_slots_mixin.py#L494).

- [x] 11) Добавить возможность читать K0/K1 из расширенных настроек температурной компенсации.
Что сделано: добавлены отдельные кнопки `Читать K1` и `Читать K0` рядом с полями расширенного блока.
Ссылки: [CalibrationCard.qml#L1214](/d:/revkovms/dev/_GUIs/tosun-geehy-can-uds-tools-git/ui/qml/components/CalibrationCard.qml#L1214), [CalibrationCard.qml#L1248](/d:/revkovms/dev/_GUIs/tosun-geehy-can-uds-tools-git/ui/qml/components/CalibrationCard.qml#L1248), [public_slots_mixin.py#L448](/d:/revkovms/dev/_GUIs/tosun-geehy-can-uds-tools-git/ui/qml/controller/public_slots_mixin.py#L448), [public_slots_mixin.py#L471](/d:/revkovms/dev/_GUIs/tosun-geehy-can-uds-tools-git/ui/qml/controller/public_slots_mixin.py#L471).

- [x] 12) Перевести рекомендацию коэффициентов в строгий оффлайн-режим: только по CSV выбранного узла, без влияния текущих DID.
Что сделано: в расчете явно зафиксирована оффлайн-логика рекомендаций по выбранному набору CSV/XLSX.
Ссылки: [calibration_mixin.py#L2676](/d:/revkovms/dev/_GUIs/tosun-geehy-can-uds-tools-git/ui/qml/controller/calibration_mixin.py#L2676), [calibration_mixin.py#L1943](/d:/revkovms/dev/_GUIs/tosun-geehy-can-uds-tools-git/ui/qml/controller/calibration_mixin.py#L1943).

- [x] 13) Добавить кнопку «Подогнать K0 к 0% при текущей температуре» (автоматический расчет по текущим DID).
Что сделано: кнопка добавлена в UI и связана со слотом автоподстройки.
Ссылки: [CalibrationCard.qml#L874](/d:/revkovms/dev/_GUIs/tosun-geehy-can-uds-tools-git/ui/qml/components/CalibrationCard.qml#L874), [public_slots_mixin.py#L494](/d:/revkovms/dev/_GUIs/tosun-geehy-can-uds-tools-git/ui/qml/controller/public_slots_mixin.py#L494).

- [x] 14) Обеспечить запись CSV только в кодировке UTF-8.
Что сделано: запись CSV выполняется через `CSV_WRITE_ENCODING = "utf-8"`.
Ссылки: [collector_csv_manager.py#L6](/d:/revkovms/dev/_GUIs/tosun-geehy-can-uds-tools-git/ui/qml/collector_csv_manager.py#L6), [collector_csv_manager.py#L36](/d:/revkovms/dev/_GUIs/tosun-geehy-can-uds-tools-git/ui/qml/collector_csv_manager.py#L36), [collector_csv_manager.py#L49](/d:/revkovms/dev/_GUIs/tosun-geehy-can-uds-tools-git/ui/qml/collector_csv_manager.py#L49).

- [x] 15) Добавить поддержку загрузки XLSX для анализа и расчета рекомендуемых K0/K1.
Что сделано: добавлена загрузка `.xlsx` (через `openpyxl`) и фильтры выбора файла в UI.
Ссылки: [requirements.txt#L5](/d:/revkovms/dev/_GUIs/tosun-geehy-can-uds-tools-git/requirements.txt#L5), [calibration_mixin.py#L1831](/d:/revkovms/dev/_GUIs/tosun-geehy-can-uds-tools-git/ui/qml/controller/calibration_mixin.py#L1831), [CalibrationCard.qml#L825](/d:/revkovms/dev/_GUIs/tosun-geehy-can-uds-tools-git/ui/qml/components/CalibrationCard.qml#L825), [CalibrationCard.qml#L2082](/d:/revkovms/dev/_GUIs/tosun-geehy-can-uds-tools-git/ui/qml/components/CalibrationCard.qml#L2082).

- [x] 16) Зафиксировать и документировать понятный алгоритм расчета K0: оффлайн-рекомендация по CSV и отдельная онлайн-подгонка K0.
Что сделано: добавлен отдельный документ с пошаговым сценарием применения K1/K0 и объяснением причин смещения на комнате.
Ссылки: [TEMP_COMP_K0_WORKFLOW.md#L1](/d:/revkovms/dev/_GUIs/tosun-geehy-can-uds-tools-git/docs/TEMP_COMP_K0_WORKFLOW.md#L1).

## Правило ведения
- Обновлять статус каждого пункта только после фактической проверки в коде/интерфейсе.
- Для каждого закрытого пункта добавлять короткую пометку «что сделано» и ссылку на файл/место изменения.
