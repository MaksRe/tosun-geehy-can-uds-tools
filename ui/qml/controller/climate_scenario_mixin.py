"""Сценарий автоматического прогона в программе: правка, файлы, применение.

ЗАЧЕМ
Сценарий испытания составляется один раз и потом используется много раз, в
том числе на другом компьютере у камеры. Поэтому он живёт файлом в папке
scenarios рядом с программой, а форма в окне правит его и сохраняет.

ЧТО ДЕЛАЕТ
- Держит текущий сценарий. Он переживает перезапуск программы (файл
  config/climate_scenario_current.json), даже если ещё не сохранён в папку.
- Принимает правки из формы целиком (JSON) и проверяет их модулем сценария.
- Новый сценарий: пустой или готовый «Испытание платы, один цикл».
- Сохраняет в scenarios/<имя>.json или в выбранный файл, загружает из списка
  или из любого файла. Первый раз сам кладёт в папку готовый сценарий.
- При старте прогона переносит из сценария в «Прогон в камере» режим «только
  плата», модель ухода, пометку и автозапись профиля.
"""

from __future__ import annotations

import json
import pathlib
import sys

from ui.qml import climate_scenario

from .contract import AppControllerContract


class AppControllerClimateScenarioMixin(AppControllerContract):

    # ------------------------------------------------------------------ состояние и файлы

    def _climate_scenario_dir(self) -> pathlib.Path:
        """Папка сценариев: scenarios рядом с программой (у собранной - рядом с exe)."""
        if getattr(sys, "frozen", False):
            return pathlib.Path(sys.executable).resolve().parent / "scenarios"
        root = getattr(self, "_project_root_directory", None) or pathlib.Path.cwd()
        return pathlib.Path(root) / "scenarios"

    def _climate_scenario_current_path(self) -> pathlib.Path:
        return self._climate_settings_path().with_name("climate_scenario_current.json")

    def _climate_scenario_init(self):
        """Текущий сценарий: с прошлого запуска, а в первый раз - из прежних настроек прогона."""
        self._climate_scenario_revision = 0
        self._climate_scenario_status = ""
        self._climate_scenario_problems: list[str] = []
        self._climate_scenario_path = ""
        self._climate_scenario_dirty = False
        self._climate_scenario_files: list[dict] = []
        try:
            stored = json.loads(self._climate_scenario_current_path().read_text(encoding="utf-8"))
            scenario, problems = climate_scenario.normalize(stored.get("scenario"))
            self._climate_scenario = scenario
            self._climate_scenario_problems = problems
            self._climate_scenario_path = str(stored.get("path") or "")
            self._climate_scenario_dirty = bool(stored.get("dirty", False))
            if int((stored.get("scenario") or {}).get("version", climate_scenario.VERSION)) < climate_scenario.VERSION:
                # Сценарий прежней версии обновлён при чтении: сохранить сразу, чтобы обновление было один раз.
                self._climate_scenario_store()
        except (OSError, ValueError, AttributeError, TypeError):
            self._climate_scenario = climate_scenario.from_settings(
                self._climate_settings,
                board_only=bool(getattr(self, "_chamber_board_only", False)),
                single_model=str(getattr(self, "_chamber_single_model", "")),
                label=str(getattr(self, "_chamber_label", "")).strip(),
                auto_write=bool(getattr(self, "_chamber_auto_write", True)))
            self._climate_scenario_dirty = True
            self._climate_scenario_store()
        self._climate_scenario_seed_folder()
        self._climate_scenario_refresh_files()

    def _climate_scenario_seed_folder(self):
        """Первый запуск: в пустую папку сценариев кладётся готовый «Испытание платы, один цикл»."""
        folder = self._climate_scenario_dir()
        try:
            if folder.exists() and any(folder.glob("*.json")):
                return
            climate_scenario.save(climate_scenario.board_cycle_scenario(),
                                  folder / climate_scenario.file_name(climate_scenario.BOARD_CYCLE_NAME))
        except OSError:
            pass

    def _climate_scenario_store(self):
        """Текущий сценарий на диск: переживает перезапуск, даже несохранённый."""
        path = self._climate_scenario_current_path()
        payload = {"scenario": self._climate_scenario, "path": self._climate_scenario_path,
                   "dirty": self._climate_scenario_dirty}
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as error:
            self._climate_scenario_status = f"Текущий сценарий не сохранился: {error}"

    def _climate_scenario_refresh_files(self):
        """Сохранённые сценарии в папке: имя файла и название сценария внутри."""
        files = []
        try:
            for path in sorted(self._climate_scenario_dir().glob("*.json")):
                try:
                    name = str(json.loads(path.read_text(encoding="utf-8")).get("name") or path.stem)
                except (OSError, ValueError, AttributeError):
                    name = f"{path.stem} (не читается)"
                files.append({"path": str(path), "file": path.name, "name": name})
        except OSError:
            pass
        self._climate_scenario_files = files

    def _climate_scenario_set(self, scenario: dict, path: str = "", dirty: bool = True, status: str = ""):
        """Новый текущий сценарий целиком: форма перечитает его (ревизия растёт)."""
        clean, problems = climate_scenario.normalize(scenario)
        self._climate_scenario = clean
        self._climate_scenario_problems = problems
        self._climate_scenario_path = str(path)
        self._climate_scenario_dirty = bool(dirty)
        self._climate_scenario_revision += 1
        self._climate_scenario_status = status
        self._climate_scenario_store()
        self.climateChanged.emit()

    # ------------------------------------------------------------------ действия формы

    def _climate_scenario_busy(self) -> bool:
        """Во время прогона сценарий не меняется: прогон идёт по тому, с которым начат."""
        if self._climate_run_stage:
            self._climate_scenario_status = "Идёт прогон: сценарий меняется только после его окончания."
            self.climateChanged.emit()
            return True
        return False

    def _climate_scenario_update(self, text: str) -> bool:
        """Правка из формы: весь сценарий строкой JSON. Ревизия не растёт - форма не перечитывается."""
        if self._climate_scenario_busy():
            return False
        try:
            data = json.loads(str(text))
        except ValueError as error:
            self._climate_scenario_status = f"Правка не принята: {error}"
            self.climateChanged.emit()
            return False
        clean, problems = climate_scenario.normalize(data)
        self._climate_scenario = clean
        self._climate_scenario_problems = problems
        self._climate_scenario_dirty = True
        self._climate_scenario_status = ""
        self._climate_scenario_store()
        self.climateChanged.emit()
        return True

    def _climate_scenario_new(self, kind: str) -> bool:
        """Новый сценарий: «board_cycle» - испытание платы за один цикл, «refill» - добор точек, иначе пустой."""
        if self._climate_scenario_busy():
            return False
        if kind == "refill":
            self._climate_scenario_set(climate_scenario.refill_scenario(),
                                       status=f"Новый сценарий «{climate_scenario.REFILL_NAME}». Перед стартом откройте "
                                              "журнал прошлого прогона: точки допишутся к нему.")
        elif kind == "assembly":
            self._climate_scenario_set(climate_scenario.assembly_scenario(),
                                       status=f"Новый сценарий «{climate_scenario.ASSEMBLY_NAME}». Перед стартом у "
                                              "каждой платы откройте журнал первого этапа: точки допишутся к нему.")
        elif kind == "board_cycle":
            self._climate_scenario_set(climate_scenario.board_cycle_scenario(),
                                       status=f"Новый сценарий «{climate_scenario.BOARD_CYCLE_NAME}». "
                                              "Сохраните его, если меняли.")
        else:
            self._climate_scenario_set(climate_scenario.empty_scenario(), status="Новый пустой сценарий.")
        return True

    def _climate_scenario_save(self, path: str = "") -> bool:
        """Сохраняет текущий сценарий: в указанный файл, в свой файл или в папку сценариев по названию."""
        target = str(path or self._climate_scenario_path or
                     self._climate_scenario_dir() / climate_scenario.file_name(self._climate_scenario["name"]))
        try:
            saved = climate_scenario.save(self._climate_scenario, target)
        except OSError as error:
            self._climate_scenario_status = f"Сценарий не сохранён: {error}"
            self.climateChanged.emit()
            return False
        self._climate_scenario_path = str(saved)
        self._climate_scenario_dirty = False
        self._climate_scenario_status = f"Сценарий сохранён: {saved}"
        self._climate_scenario_store()
        self._climate_scenario_refresh_files()
        self._climate_diag_event("SCENARIO", f"сохранён «{self._climate_scenario['name']}»: {saved}")
        self.climateChanged.emit()
        return True

    def _climate_scenario_load(self, path: str) -> bool:
        """Загружает сценарий из файла; замечания по неверным полям показываются в форме."""
        if self._climate_scenario_busy():
            return False
        try:
            scenario, problems = climate_scenario.load(path)
        except (OSError, ValueError) as error:
            self._climate_scenario_status = f"Сценарий не загрузился: {error}"
            self.climateChanged.emit()
            return False
        tail = f" Замечаний: {len(problems)} - смотрите ниже." if problems else ""
        self._climate_scenario_set(scenario, path=str(path), dirty=bool(problems),
                                   status=f"Загружен сценарий «{scenario['name']}».{tail}")
        self._climate_scenario_problems = problems
        self._climate_diag_event("SCENARIO", f"загружен «{scenario['name']}» из {path}")
        return True

    def _climate_scenario_apply_chamber(self):
        """Настройки расчёта из сценария - в «Прогон в камере»: режим, модель, пометка, автозапись."""
        scenario = getattr(self, "_climate_scenario", None)
        if not scenario:
            return
        set_board = getattr(self, "_chamber_set_board_only", None)
        if set_board is not None:
            set_board(bool(scenario["board_only"]))
        set_model = getattr(self, "_chamber_set_single_model", None)
        if set_model is not None:
            set_model(scenario["single_model"])
        labels = scenario.get("labels") or []
        if labels:
            self._chamber_label = labels[0]
        self._chamber_auto_write = bool(scenario["auto_write"])
        changed = getattr(self, "chamberChanged", None)
        if changed is not None:
            changed.emit()

    def _climate_scenario_use_board_cycle(self) -> str:
        """Кнопка быстрой настройки: готовый сценарий испытания платы и его настройки расчёта."""
        self._climate_scenario_new("board_cycle")
        self._climate_scenario_apply_chamber()
        if self._climate_settings["driver"] != "simulator":
            set_test = getattr(self, "_chamber_test_set_mode", None)
            if set_test is not None:
                set_test(False)
        text = (f"Выбран сценарий «{climate_scenario.BOARD_CYCLE_NAME}»: "
                f"{climate_scenario.summary(self._climate_scenario)}.")
        self._climate_command_status = text
        self.climateChanged.emit()
        return text

    # ------------------------------------------------------------------ показ

    def _climate_scenario_view(self) -> dict:
        """Сценарий для формы и блока автопрогона."""
        scenario = getattr(self, "_climate_scenario", None) or climate_scenario.empty_scenario()
        path = self._climate_scenario_path
        return {
            "scenario": scenario,
            "revision": int(self._climate_scenario_revision),
            "summary": climate_scenario.summary(scenario),
            "path": path,
            "fileName": pathlib.Path(path).name if path else "",
            "dirty": bool(self._climate_scenario_dirty),
            "problems": list(self._climate_scenario_problems),
            "status": self._climate_scenario_status,
            "files": list(self._climate_scenario_files),
            "folder": str(self._climate_scenario_dir()),
            "folderUrl": self._climate_scenario_dir().as_uri() if self._climate_scenario_dir().is_absolute() else "",
            "locked": bool(self._climate_run_stage),
            # Идущий шаг прогона: пройденные шаги в форме не правятся. -1 - прогон не идёт.
            "runIndex": int(self._climate_run_index) if self._climate_run_stage else -1,
        }
