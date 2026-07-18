from flask import current_app, jsonify


def _blocked(code, message):
    return jsonify({"code": code, "message": message}), 403


def release_legacy_mutation_error(code, message):
    profile = str(current_app.config.get("RUNTIME_PROFILE", "DEVELOPMENT")).upper()
    if profile != "RELEASE" or current_app.config.get("LEGACY_MIGRATION_MODE", False):
        return None
    return _blocked(code, message)


def manual_sync_mutation_error():
    profile = str(current_app.config.get("RUNTIME_PROFILE", "DEVELOPMENT")).upper()
    migration_mode = current_app.config.get("LEGACY_MIGRATION_MODE", False)
    testing_mode = current_app.config.get("TESTING", False) and profile != "RELEASE"
    if migration_mode or testing_mode:
        return None
    return _blocked(
        "MANUAL_SYNC_DISABLED",
        "El estado de sincronizacion no puede cambiarse manualmente",
    )
