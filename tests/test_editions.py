import json
from pathlib import Path

import pytest

from edition import Edition, get_edition_config, resolve_database_path
from ferreteria_core import Database
from updater_core import apply_update, load_package, read_installed_edition, validate_installation


def _installation(root: Path, edition: Edition):
    config=get_edition_config(edition);root.mkdir();(root/"PuntoDeVenta.exe").write_bytes(b"old");(root/"_internal").mkdir()
    (root/"version.json").write_text(json.dumps({"version":"1.1.4","edition":edition.value}),encoding="utf-8")
    Database(root/config.database_relative_path).migrate()
    return validate_installation(root)


def _package(root: Path, edition: Edition):
    payload=root/"payload";payload.mkdir(parents=True);(payload/"PuntoDeVenta.exe").write_bytes(b"new");(payload/"_internal").mkdir()
    (root/"version.json").write_text(json.dumps({"version":"1.1.4","edition":edition.value,"required_schema_min":8,"target_schema":8}),encoding="utf-8")
    return load_package(root)


def test_ferreteria_conserva_identidad_y_ruta_actual():
    config=get_edition_config(Edition.FERRETERIA)
    assert config.app_name=="Ferretería POS" and config.database_relative_path==Path("data/ferreteria.db") and config.truper_enabled


def test_sin_configuracion_selecciona_ferreteria():
    assert get_edition_config(environ={}).edition is Edition.FERRETERIA


def test_rutas_de_base_por_edicion(tmp_path):
    assert resolve_database_path(tmp_path,Edition.FERRETERIA,environ={})==tmp_path/"data/ferreteria.db"
    assert resolve_database_path(tmp_path,Edition.GENERAL,environ={})==tmp_path/"data/punto_venta.db"


def test_general_ignora_completamente_override_legacy_ferreteria(tmp_path):
    legacy=tmp_path/"data/ferreteria.db"
    resolved=resolve_database_path(tmp_path,Edition.GENERAL,environ={"FERRETERIA_DB":str(legacy)})
    assert resolved==tmp_path/"data/punto_venta.db" and resolved!=legacy


def test_override_general_es_exclusivo_de_general(tmp_path):
    general=tmp_path/"general_separada.db";environment={"PUNTO_VENTA_GENERAL_DB":str(general)}
    assert resolve_database_path(tmp_path,Edition.GENERAL,environ=environment)==general
    assert resolve_database_path(tmp_path,Edition.FERRETERIA,environ=environment)==tmp_path/"data/ferreteria.db"


def test_override_legacy_se_conserva_solo_para_ferreteria(tmp_path):
    legacy=tmp_path/"legacy.db";environment={"FERRETERIA_DB":str(legacy)}
    assert resolve_database_path(tmp_path,Edition.FERRETERIA,environ=environment)==legacy
    assert resolve_database_path(tmp_path,Edition.GENERAL,environ=environment)==tmp_path/"data/punto_venta.db"


def test_general_inicializa_identidad_y_base_independientes(tmp_path):
    config=get_edition_config(Edition.GENERAL);database=Database(tmp_path/config.database_relative_path);database.migrate()
    assert config.app_name=="PuntoDeVenta General" and database.path.name=="punto_venta.db" and not config.truper_enabled


def test_metadatos_antiguos_sin_edicion_son_ferreteria(tmp_path):
    root=tmp_path/"metadata";root.mkdir();(root/"version.json").write_text('{"version":"1.1.4"}',encoding="utf-8")
    assert read_installed_edition(root) is Edition.FERRETERIA


def test_paquete_antiguo_sin_edicion_es_ferreteria(tmp_path):
    root=tmp_path/"package";package=_package(root,Edition.FERRETERIA)
    metadata=json.loads((root/"version.json").read_text(encoding="utf-8"));metadata.pop("edition");(root/"version.json").write_text(json.dumps(metadata),encoding="utf-8")
    assert load_package(root).edition is Edition.FERRETERIA


def test_instalacion_antigua_sin_edicion_es_ferreteria(tmp_path):
    root=tmp_path/"install";installation=_installation(root,Edition.FERRETERIA)
    (root/"version.json").write_text('{"version":"1.1.4"}',encoding="utf-8")
    detected=validate_installation(root)
    assert installation.database.valid and detected.edition is Edition.FERRETERIA and detected.database.path==root/"data/ferreteria.db"


@pytest.mark.parametrize("installed,package",[(Edition.FERRETERIA,Edition.GENERAL),(Edition.GENERAL,Edition.FERRETERIA)])
def test_actualizador_rechaza_edicion_cruzada_sin_tocar_base(tmp_path,installed,package):
    installation=_installation(tmp_path/"install",installed);update=_package(tmp_path/"package",package)
    database=installation.database.path;before=database.read_bytes()
    with pytest.raises(RuntimeError,match="edición"):apply_update(update,installation,running_check=lambda:False)
    assert database.read_bytes()==before and not (installation.path/"backups").exists()


@pytest.mark.parametrize("name",["ferreteria.db","punto_venta.db","OTRA.DB"])
def test_paquete_no_admite_ninguna_base_de_datos(tmp_path,name):
    root=tmp_path/name.replace(".","_");package=_package(root,Edition.FERRETERIA);(package.payload/name).write_bytes(b"db")
    with pytest.raises(ValueError,match="base de datos"):load_package(root)
