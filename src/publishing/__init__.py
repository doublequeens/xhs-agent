from .artifacts import (
    CANONICAL_CONTRACT_FILES,
    PublishArtifacts,
    PublishAttestation,
    build_content_lock,
    build_publish_copy,
    canonical_content_bytes,
    export_publish_package,
)

__all__ = [
    "CANONICAL_CONTRACT_FILES",
    "PublishArtifacts",
    "PublishAttestation",
    "build_content_lock",
    "build_publish_copy",
    "canonical_content_bytes",
    "export_publish_package",
    # v4 exporters are resolved lazily: importing them eagerly would cycle
    # through src.nodes.v4 (which imports this package's v3 artifacts module)
    # back into the review modules the v4 exporters verify through.
    "PublishArtifactsV4",
    "V4_PUBLISH_ROOT",
    "export_v4_publish_package",
    "SHADOW_ROOT",
    "ShadowBundleV4",
    "export_v4_shadow_bundle",
]

_LAZY_EXPORTS = {
    "PublishArtifactsV4": ("v4_artifacts", "PublishArtifactsV4"),
    "V4_PUBLISH_ROOT": ("v4_artifacts", "V4_PUBLISH_ROOT"),
    "export_v4_publish_package": ("v4_artifacts", "export_v4_publish_package"),
    "SHADOW_ROOT": ("shadow_artifacts", "SHADOW_ROOT"),
    "ShadowBundleV4": ("shadow_artifacts", "ShadowBundleV4"),
    "export_v4_shadow_bundle": ("shadow_artifacts", "export_v4_shadow_bundle"),
}


def __getattr__(name: str):
    try:
        module_name, attribute = _LAZY_EXPORTS[name]
    except KeyError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None
    from importlib import import_module

    module = import_module(f".{module_name}", __package__)
    return getattr(module, attribute)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_LAZY_EXPORTS))
