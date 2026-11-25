import QtQuick 2.15
import QtQuick.Layouts 1.15
import QtQuick.Dialogs
import "."

SpoilerSection {
    id: panel

    property var appController
    property int selectedAddress: -1
    property var choices: []
    property string notice: ""
    property string noticeTone: "normal"
    property string fileError: ""
    readonly property var check: appController ? appController.chamberTubeCheck : ({})
    readonly property var scan: appController ? appController.chamberTubeScan : ({})
    readonly property var boards: check.boards || []
    readonly property var result: boards.find(board => board.sa === selectedAddress) || boards[0] || ({})
    readonly property int address: result.sa === undefined ? -1 : result.sa

    title: "Проверка монтажа трубок"
    hintText: boards.length ? "Плат для проверки: " + boards.length : "Жду ответы плат"
    expanded: true
    headerHeight: 36
    contentPadding: 10
    cardColor: "#f8fafc"
    cardBorder: "#e2e8f0"
    accentColor: "#0f766e"

    onBoardsChanged: {
        const next = boards.map(board => ({ sa: board.sa, node: board.node }))
        if (JSON.stringify(next) !== JSON.stringify(choices))
            choices = next
    }
    onAddressChanged: fileError = ""

    component Caption: Text {
        color: panel.textSoft
        font.pixelSize: 12
        font.family: "Bahnschrift"
        wrapMode: Text.WordWrap
    }

    component SmallButton: FancyButton {
        implicitHeight: 28
        height: implicitHeight
        fontPixelSize: 12
        tone: "#64748b"
        toneHover: "#475569"
        tonePressed: "#334155"
    }

    // Пустое измерение показывает прочерком, а для положительной разницы добавляет знак.
    function reading(value, signed) {
        if (value === null || value === undefined)
            return "—"
        return (signed && Number(String(value).replace(",", ".")) > 0 ? "+" : "") + value
    }

    // Для сравнения всех узлов выводит оба контура каждой платы в общей таблице.
    function summaryRows(boards) {
        const rows = []
        for (const board of boards) {
            for (const key of ["main", "media"]) {
                const row = (board.rows || []).find(channel => channel.key === key) || {}
                const status = board.status || (!board.baseline ? "Нет журнала голой платы"
                    : row.note || (row.delta == null ? "Нет данных для сравнения" : "Есть замер"))
                rows.push({
                    tone: row.delta != null && !row.note ? "info" : "warn",
                    cells: {
                        node: board.node, channel: key === "main" ? "Основной" : "Вид топлива",
                        delta: panel.reading(row.delta, true), pf: panel.reading(row.pf, true),
                        dry: panel.reading(row.dryDelta, true),
                        temperature: (board.temperature || "—").replace(" °C", ""),
                        base: panel.reading(row.baseline, false), now: panel.reading(row.current, false),
                        spread: panel.reading(row.spread, false), status: status
                    }
                })
            }
        }
        return rows
    }

    FileDialog {
        id: choose
        property int targetAddress: -1
        property bool reference: false
        title: reference ? "Выберите журнал с замером сухих трубок" : "Выберите журнал голой платы"
        fileMode: FileDialog.OpenFile
        nameFilters: ["Журналы прогона (*.csv)"]
        onAccepted: {
            if (panel.appController)
                panel.fileError = panel.appController.loadChamberTubeJournal(targetAddress, selectedFile.toString(), reference)
        }
    }

    ColumnLayout {
        Layout.fillWidth: true
        spacing: 6
        Caption {
            Layout.fillWidth: true
            text: "Оставьте трубки сухими на воздухе. Для сравнения используются точки голой платы «0/0» при близкой температуре."
        }

        Flow {
            Layout.fillWidth: true
            spacing: 8

            Row {
                height: 28
                spacing: 6
                Caption { text: "От (HEX)"; anchors.verticalCenter: parent.verticalCenter }
                FancyTextField {
                    id: scanStart
                    topPadding: 2
                    bottomPadding: 2
                    verticalAlignment: TextInput.AlignVCenter
                    width: 85
                    height: 28
                    text: panel.scan.startText || "0x80"
                    enabled: panel.check.scanAllowed === true && !panel.scan.active
                }
                Caption { text: "До"; anchors.verticalCenter: parent.verticalCenter }
                FancyTextField {
                    id: scanEnd
                    topPadding: 2
                    bottomPadding: 2
                    verticalAlignment: TextInput.AlignVCenter
                    width: 85
                    height: 28
                    text: panel.scan.endText || "0x8F"
                    enabled: panel.check.scanAllowed === true && !panel.scan.active
                }
            }

            SmallButton {
                objectName: "tubeFindBoards"
                text: panel.scan.active ? "Остановить поиск" : "Найти платы"
                enabled: !!panel.appController && (panel.scan.active ? !panel.scan.stopping : !!panel.check.scanAllowed)
                tone: "#0284c7"; toneHover: "#0369a1"; tonePressed: "#075985"
                toolTipText: "Ищет платы по CAN в заданном диапазоне, в том числе с отключённым Tx. Поиск доступен вне прогона."
                onClicked: {
                    panel.notice = ""
                    if (panel.scan.active)
                        panel.appController.stopBoardScan()
                    else
                        panel.appController.startChamberTubeScan(scanStart.text, scanEnd.text)
                }
            }

            SmallButton {
                objectName: "tubeFindBaselines"
                text: "Найти журналы всем платам"
                enabled: !!panel.appController && panel.boards.length > 0 && !panel.scan.active
                toolTipText: "Подбирает базу по CAN-адресу для каждой платы, у которой ещё нет журнала."
                onClicked: {
                    const found = panel.appController.findChamberTubeBaselines()
                    const missing = found.missing || []
                    panel.noticeTone = missing.length ? "warn" : "ok"
                    panel.notice = "Найдено журналов: " + found.found + ". Уже выбрано: " + found.kept + "."
                                 + (missing.length ? " Выберите CSV для " + missing.join(", ") + "." : "")
                }
            }
        }

        NoticeLine {
            appController: panel.appController
            text: panel.notice || panel.scan.status || ""
            title: panel.notice
            tone: panel.notice ? panel.noticeTone : (panel.scan.tone || "normal")
            kind: "Проверка трубок"
        }

        ResultsTable {
            objectName: "tubeSummary"
            visible: panel.boards.length > 0
            table: ({
                title: "Сводная таблица проверки трубок",
                tip: "У каждой платы два контура. Прибавка рассчитана относительно голой платы при той же температуре. Последний столбец отклонений сравнивает показание с прошлым замером сухой трубки.",
                columns: [
                    { key: "node", title: "Узел CAN", width: 125, align: "left" },
                    { key: "channel", title: "Контур", width: 100, align: "left" },
                    { key: "delta", title: "Δ к плате, отсч.", width: 90 },
                    { key: "pf", title: "Δ ≈ пФ", width: 72 },
                    { key: "dry", title: "Δ к сухой трубке, отсч.", width: 124,
                      tip: "Разница с прошлым замером на воздухе при близких температурах платы и трубки." },
                    { key: "temperature", title: "Плата, °C", width: 78 },
                    { key: "base", title: "Голая плата, отсч.", width: 96 },
                    { key: "now", title: "Сейчас, отсч.", width: 85 },
                    { key: "spread", title: "Разброс, отсч.", width: 85 },
                    { key: "status", title: "Состояние", width: 225, align: "left" }
                ],
                rows: panel.summaryRows(panel.boards)
            })
        }

        RowLayout {
            Layout.fillWidth: true
            visible: panel.boards.length > 0
            spacing: 8
            Caption { text: "Подробности по плате"; font.bold: true }
            FancyComboBox {
                objectName: "tubeBoardChoice"
                Layout.preferredWidth: 195
                Layout.preferredHeight: 30
                model: panel.choices
                textRole: "node"
                currentIndex: panel.choices.findIndex(board => board.sa === panel.address)
                onActivated: panel.selectedAddress = panel.choices[index].sa
            }
            Item { Layout.fillWidth: true }
        }

        Flow {
            Layout.fillWidth: true
            visible: panel.address >= 0
            spacing: 6

            SmallButton {
                objectName: "tubeChooseBaseline"
                text: "Выбрать базу CSV…"
                onClicked: {
                    choose.targetAddress = panel.address
                    choose.reference = false
                    choose.open()
                }
            }
            SmallButton {
                text: "Прошлый замер «воздух»…"
                enabled: !!panel.result.baseline
                onClicked: {
                    choose.targetAddress = panel.address
                    choose.reference = true
                    choose.open()
                }
            }
            SmallButton {
                visible: !!panel.result.reference
                text: "Убрать прошлый замер"
                onClicked: panel.fileError = panel.appController.loadChamberTubeJournal(panel.address, "", true)
            }
        }

        Caption {
            Layout.fillWidth: true
            visible: !!panel.result.baseline
            text: "База · " + (panel.result.baseline || "")
            wrapMode: Text.WrapAnywhere
        }
        Caption {
            Layout.fillWidth: true
            visible: !!panel.result.reference
            text: "Прошлый замер · " + (panel.result.reference || "")
            wrapMode: Text.WrapAnywhere
        }
        NoticeLine {
            appController: panel.appController
            text: panel.fileError || (panel.result.unsigned
                ? "В имени одного из файлов нет адреса. Проверьте, что он относится к выбранной плате." : "")
            tone: panel.fileError ? "bad" : "warn"
            kind: "Журналы"
        }
        NoticeLine {
            appController: panel.appController
            text: panel.result.status || panel.result.referenceStatus || ""
            tone: panel.result.status ? "warn" : "normal"
            kind: "Измерения"
        }

        Repeater {
            model: panel.result.rows || []
            delegate: Caption {
                required property var modelData
                Layout.fillWidth: true
                text: modelData.label + " · " + modelData.detail
            }
        }
    }
}
