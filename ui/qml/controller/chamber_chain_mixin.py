"""Запись посчитанного профиля в прибор одной операцией из раздела прогона.

ЗАЧЕМ
После расчёта таблиц оператор раньше шёл в раздел «Температурный профиль» и
руками проходил пять шагов: проверить таблицы, нажать «Начать калибровку»,
«Записать в прибор», «Проверить запись» и «Сохранить в файл». Шаги всегда одни и
те же и идут в одном порядке, поэтому раздел прогона делает их сам.

КАК ИДЁТ
1. Доступ: если калибровка не запущена, запускает её, как кнопка «Начать
   калибровку», и ждёт, пока прибор откроет запись.
2. Запись: пишет таблицы, номер алгоритма, поколение и в самом конце сумму.
3. Сверка: читает профиль обратно и сравнивает с таблицами на экране.
4. Файл: сохраняет записанный профиль рядом с журналом прогона. Это откат и
   перенос на другой прибор.

Запускается кнопкой или сама, когда данных хватило во всех узлах и таблицы
изменились с прошлой записи. Точки пробной калибровки в прибор не пишутся никогда.
"""

from __future__ import annotations

import pathlib
import time
from datetime import datetime

from PySide6.QtCore import QTimer

from .bus_guard import background_request_recent
from .contract import AppControllerContract


class AppControllerChamberChainMixin(AppControllerContract):
    # Такт проверки хода цепочки, мс.
    CHAMBER_CHAIN_TICK_MS = 200
    # Сколько ждать доступа на запись, с.
    CHAMBER_CHAIN_ACCESS_TIMEOUT_S = 20.0
    # Сколько ждать записи вместе со сверкой, с. Таблицы идут мультипакетом.
    CHAMBER_CHAIN_WRITE_TIMEOUT_S = 90.0

    CHAMBER_CHAIN_STEPS = (
        ("access", "Доступ на запись"),
        ("write", "Запись в прибор"),
        ("verify", "Сверка с прибором"),
        ("file", "Сохранение в файл"),
    )

    # ------------------------------------------------------------------ состояние

    def _init_chamber_chain_state(self):
        """Готовит цепочку записи профиля. Вызывается один раз при создании контроллера."""
        # Писать ли профиль в прибор самому, когда данных хватило во всех узлах.
        self._chamber_auto_write = True
        self._chamber_chain_stage = ""
        self._chamber_chain_steps = {key: "" for key, _title in self.CHAMBER_CHAIN_STEPS}
        self._chamber_chain_status = "Профиль в прибор ещё не записывался."
        self._chamber_chain_color = "#64748b"
        self._chamber_chain_deadline = 0.0
        self._chamber_chain_crc = None
        # Сумма профиля, который последним записан и сверен: повторно тот же не пишется.
        self._chamber_written_crc = None

        self._chamber_chain_timer = QTimer(self)
        self._chamber_chain_timer.setInterval(self.CHAMBER_CHAIN_TICK_MS)
        self._chamber_chain_timer.timeout.connect(self._on_chamber_chain_tick)

    def _chamber_chain_set(self, text: str, color: str):
        """Строка хода цепочки и уведомление окну."""
        self._chamber_chain_status = str(text)
        self._chamber_chain_color = str(color)
        self.chamberChanged.emit()

    def _chamber_chain_write_ready(self) -> bool:
        """Открыт ли доступ на запись именно в выбранный прибор."""
        if not (bool(self._calibration_active) and bool(self._calibration_session_ready)):
            return False
        if self._service_access_target_sa is None or not self._service_security_unlocked:
            return False
        return (int(self._service_access_target_sa) & 0xFF) == (int(self._resolve_calibration_target_sa()) & 0xFF)

    # ------------------------------------------------------------------ запуск

    def _chamber_chain_problem(self) -> str:
        """Причина, по которой писать профиль сейчас нельзя, или пустая строка."""
        if not self._chamber_points:
            return "в журнале нет ни одной точки"
        if any(point.get("rehearsal") for point in self._chamber_points):
            return "в журнале есть точки пробной калибровки, их таблицы в прибор писать нельзя"
        if self._chamber_busy or getattr(self, "_chamber_capture_waiting", False):
            return "идёт снятие точки"
        if bool(getattr(self, "_trial_busy", False)):
            return "идёт пробная калибровка"
        if bool(self._profile_busy) or bool(self._options_busy):
            return "идёт другой обмен профилем или параметрами"
        problems = self._profile_validate()
        if problems:
            return problems[0]
        if not self._can.is_connect or not self._can.is_trace:
            return "нет связи: подключите адаптер и включите трассировку"
        return ""

    def _chamber_chain_start(self, automatic: bool = False) -> bool:
        """Запускает цепочку: доступ, запись, сверка, файл."""
        if self._chamber_chain_stage:
            return False

        problem = self._chamber_chain_problem()
        if problem:
            if not automatic:
                self._chamber_chain_set(f"Профиль не записан: {problem}.", "#dc2626")
            return False

        # Таблицы, которые уже записаны и сверены, второй раз писать незачем.
        crc = self._profile_calc_crc()
        if automatic and self._chamber_written_crc == crc:
            return False

        self._chamber_chain_crc = crc
        self._chamber_chain_steps = {key: "" for key, _title in self.CHAMBER_CHAIN_STEPS}
        self._chamber_chain_steps["access"] = "run"
        self._chamber_chain_stage = "access"
        self._chamber_chain_deadline = time.monotonic() + self.CHAMBER_CHAIN_ACCESS_TIMEOUT_S

        who = "Данных хватило во всех узлах, пишу профиль сама" if automatic else "Пишу профиль в прибор"
        if self._chamber_chain_write_ready():
            self._chamber_chain_set(f"{who}: доступ на запись уже открыт.", "#0f6ab4")
        else:
            if not bool(self._calibration_active):
                # Та же операция, что кнопка «Начать калибровку»: сессия и доступ на запись.
                self.toggleCalibration()
            self._chamber_chain_set(f"{who}: открываю доступ на запись...", "#0f6ab4")
        self._chamber_chain_timer.start()
        return True

    def _chamber_chain_maybe_auto(self):
        """Сама запускает запись, если это разрешено и таблицы изменились с прошлой записи."""
        if not self._chamber_auto_write or self._chamber_chain_stage:
            return
        if not self._chamber_tables_complete:
            return
        self._chamber_chain_start(automatic=True)

    # ------------------------------------------------------------------ ход

    def _on_chamber_chain_tick(self):
        """Следит за текущим шагом и переходит к следующему."""
        stage = self._chamber_chain_stage
        now = time.monotonic()
        if not stage:
            self._chamber_chain_timer.stop()
            return

        if stage == "access":
            # Ответ на только что ушедший фоновый запрос ещё в пути: первая таблица его затёрла бы.
            if self._chamber_chain_write_ready() and not background_request_recent(self):
                self._chamber_chain_steps["access"] = "ok"
                self._chamber_chain_begin_write()
                return
            if now > self._chamber_chain_deadline:
                if not bool(self._calibration_active):
                    reason = "калибровка не запустилась"
                elif not bool(self._calibration_session_ready):
                    reason = "прибор не подтвердил сессию"
                else:
                    reason = "Security Access открыт не для выбранного прибора"
                self._chamber_chain_fail(
                    "access",
                    f"доступ на запись не открылся за {int(self.CHAMBER_CHAIN_ACCESS_TIMEOUT_S)} с: {reason}. "
                    "Проверьте выбор прибора в шапке окна")
            return

        if stage == "write":
            self._chamber_chain_follow_write(now)

    def _chamber_chain_begin_write(self):
        """Шаг записи: пишет таблицы в прибор, сверка запустится сама после записи."""
        # Таблицы могли измениться, пока открывался доступ: пишется то, что на экране сейчас.
        self._chamber_chain_crc = self._profile_calc_crc()
        # Расхождения прошлой сверки к этой записи не относятся.
        self._profile_verify_report = []
        if not self._profile_write_to_device():
            self._chamber_chain_fail("write", self._profile_status)
            return
        self._chamber_chain_stage = "write"
        self._chamber_chain_steps["write"] = "run"
        self._chamber_chain_deadline = time.monotonic() + self.CHAMBER_CHAIN_WRITE_TIMEOUT_S
        self._chamber_chain_set(
            f"Пишу профиль в прибор, сумма 0x{self._chamber_chain_crc:04X}...", "#0f6ab4")

    def _chamber_chain_follow_write(self, now: float):
        """Следит за записью и сверкой: обе идут очередью раздела профиля."""
        # Идёт сверка: запись к этому моменту закончилась успешно.
        if self._profile_verify is not None and self._chamber_chain_steps["verify"] != "run":
            self._chamber_chain_steps["write"] = "ok"
            self._chamber_chain_steps["verify"] = "run"
            self._chamber_chain_set("Профиль записан, сверяю с прибором...", "#0f6ab4")
            return

        result = self._profile_last_result
        if self._profile_busy or result is None:
            if now > self._chamber_chain_deadline:
                self._chamber_chain_fail(
                    "verify" if self._chamber_chain_steps["verify"] == "run" else "write",
                    f"прибор не закончил обмен за {int(self.CHAMBER_CHAIN_WRITE_TIMEOUT_S)} с")
            return

        if result != "ok":
            # Сверка могла пройти целиком между двумя тактами: её выдаёт список расхождений.
            verified = self._chamber_chain_steps["verify"] == "run" or bool(self._profile_verify_report)
            step = "verify" if verified else "write"
            if step == "verify" and self._profile_verify_report:
                reason = f"сверка не прошла: {self._profile_verify_report[0]}"
            else:
                reason = self._profile_status
            self._chamber_chain_fail(step, reason)
            return

        self._chamber_chain_steps["write"] = "ok"
        self._chamber_chain_steps["verify"] = "ok"
        self._chamber_chain_save_file()

    def _chamber_chain_profile_path(self) -> str:
        """Файл профиля: рядом с журналом прогона, с тем же именем и пометкой «профиль»."""
        journal = str(self._chamber_file_path or "")
        if journal:
            target = pathlib.Path(journal)
            return str(target.with_name(f"{target.stem}_profile.json"))
        root = getattr(self, "_project_root_directory", None)
        folder = pathlib.Path(root) / "logs" / "chamber" if root is not None else pathlib.Path.cwd()
        return str(folder / f"profile_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")

    def _chamber_chain_save_file(self):
        """Последний шаг: сохраняет записанный и сверенный профиль в файл."""
        self._chamber_chain_steps["file"] = "run"
        path = self._chamber_chain_profile_path()
        crc = int(self._chamber_chain_crc or 0)
        # Запись и сверка прошли: даже если файл не сохранится, в приборе профиль верный.
        self._chamber_written_crc = crc
        if not self._profile_save_file(path):
            self._chamber_chain_fail(
                "file", f"профиль записан и сверен, но файл не сохранился: {self._profile_status}")
            return
        self._chamber_chain_steps["file"] = "ok"
        self._profile_set_status(
            f"Профиль записан в прибор, сверен и сохранён в файл {pathlib.Path(path).name}. "
            f"Сумма 0x{crc:04X}.", "#16a34a")
        self._chamber_chain_finish(
            f"Профиль записан в прибор, сверен и сохранён: {pathlib.Path(path).name}. Сумма 0x{crc:04X}.",
            "#16a34a")

    def _chamber_chain_fail(self, step: str, reason: str):
        """Останавливает цепочку на шаге и называет причину."""
        self._chamber_chain_steps[step] = "fail"
        self._chamber_chain_finish(f"Профиль не записан до конца: {reason}", "#dc2626")

    def _chamber_chain_finish(self, text: str, color: str):
        """Завершает цепочку и выполняет пересчёт, отложенный на время записи."""
        self._chamber_chain_stage = ""
        self._chamber_chain_timer.stop()
        self._chamber_chain_set(text, color)
        if self._chamber_tables_deferred:
            # Пока шла запись, пришли новые точки: пересчёт может снова запустить запись.
            self._chamber_auto_compute()
            self.chamberChanged.emit()

    # ------------------------------------------------------------------ показ

    def _chamber_chain_view(self) -> dict:
        """Ход цепочки для окна: шаги с отметками и строка итога."""
        return {
            "busy": bool(self._chamber_chain_stage),
            "autoWrite": bool(self._chamber_auto_write),
            "status": str(self._chamber_chain_status),
            "color": str(self._chamber_chain_color),
            "steps": [
                {"title": title, "state": str(self._chamber_chain_steps.get(key, ""))}
                for key, title in self.CHAMBER_CHAIN_STEPS
            ],
        }
