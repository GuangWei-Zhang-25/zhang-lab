"""AtlasCraft: source-preserving atlas reconstruction with bounded agent review."""
__version__ = "2.0.0"


def run_pipeline(*args, **kwargs):
    """Run AtlasCraft; see :func:`atlascraft.pipeline.run_pipeline`."""
    from .pipeline import run_pipeline as run
    return run(*args, **kwargs)


def build_atlas(source, output_dir, *, api_token=None, model=None,
                api_base_url=None, api_style='responses', options=None, progress=None):
    """One-function API: curated input -> aligned volume and offline 3D viewer.

    Supply your own API token, base URL and model to enable tool orchestration.
    Omit all provider fields to run local deterministic tools without a network
    request. API credentials are not saved in the atlas or audit trail.
    """
    if any(value is not None for value in (api_token, model, api_base_url)):
        if not model or not api_base_url:
            raise ValueError('Supply both model and api_base_url when enabling an agent.')
        from .agent import HTTPProvider, ProviderConfig
        with HTTPProvider(ProviderConfig(base_url=api_base_url, model=model,
                          api_key=api_token or '', api_style=api_style)) as provider:
            return run_pipeline(source, output_dir, options=options, provider=provider, progress=progress)
    return run_pipeline(source, output_dir, options=options, progress=progress)
