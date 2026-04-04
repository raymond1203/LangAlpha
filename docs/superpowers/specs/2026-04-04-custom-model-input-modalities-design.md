# Custom Model Input Modalities

Allow users to declare input modalities (text, image, pdf) for custom models so that vision-capable local models (e.g., llava on Ollama) can receive image and PDF attachments.

## Problem

`models.json` defines `input_modalities` for every system model. Custom models stored in user preferences have no modality field and always default to `["text"]`. This means image/PDF attachments are never sent natively to custom models, even when the underlying model supports them.

## Design

### Allowed values

`text`, `image`, `pdf` — matching the existing `models.json` vocabulary. `text` is always implicitly present (cannot be removed). `video` exists in models.json for Gemini but is excluded from the custom model UI since no local provider supports it today.

### Data model

Add an optional `input_modalities` field to custom model entries in user preferences.

**Frontend type** (`web/src/components/model/types.ts`):

```typescript
interface CustomModelEntry {
  name: string;
  model_id: string;
  provider: string;
  parameters?: Record<string, unknown>;
  extra_body?: Record<string, unknown>;
  input_modalities?: string[];  // e.g., ["text", "image", "pdf"]
}
```

**Backend persistence**: stored in `user_preferences.other_preference.custom_models[].input_modalities` (existing JSONB column, no migration needed).

**Default**: `["text"]` when the field is omitted or absent. This preserves backward compatibility — existing custom models without the field behave exactly as before.

### Backend validation

In `src/server/app/users.py`, inside the custom models validation block (~line 338):

- If `input_modalities` is present, validate it is a `list` of strings.
- Each value must be in `{"text", "image", "pdf"}`.
- Ensure `"text"` is always included (add it if missing, or reject if explicitly excluded — adding it silently is simpler).
- Empty list is invalid.

### Backend resolution

Currently `get_input_modalities(model_name)` in `src/llms/llm.py` (line 691) only checks `models.json`. Change:

Add an optional `custom_modalities` override parameter:

```python
def get_input_modalities(
    model_name: str,
    custom_modalities: list[str] | None = None,
) -> list[str]:
    if custom_modalities is not None:
        return custom_modalities
    return LLM.get_model_config().get_input_modalities(model_name)
```

The caller is responsible for looking up custom model modalities from the resolved config and passing them in.

### Workflow integration

Both `ptc_workflow.py` (line 322) and `flash_workflow.py` (line 243) already have access to the resolved `config` object and `effective_model`. The change:

1. Look up the custom model config from preferences (via `get_custom_model_config(user_id, effective_model)`).
2. If found and `input_modalities` is present, pass it as `custom_modalities` to `get_input_modalities()`.
3. If not found or field absent, call as before (falls back to `models.json` then `["text"]`).

Both workflows already call `get_custom_model_config` earlier in the flow (inside `resolve_llm_config`), so the preference data is already cached in the request context.

### Frontend UI

In `ConnectStep.tsx`, after the model name/ID inputs, add a "Capabilities" row with toggle chips:

- **Text** — always on, non-interactive (greyed out / checked)
- **Image** — toggleable, off by default
- **PDF** — toggleable, off by default

The chips map directly to the `input_modalities` array. When saving, only include `input_modalities` in the entry if the user enabled image or pdf (omit the field entirely if text-only, keeping payloads minimal).

### API surface

No new endpoints. The existing `PUT /api/v1/users/me/preferences` endpoint already handles `custom_models` — the new field flows through the existing JSONB column.

The `GET /api/v1/models` response's `model_metadata` map does not currently include `input_modalities` for any model. This is unchanged — the frontend does not need modality info for display purposes (badges show access tier, not capabilities). The modality data is consumed server-side only, in the multimodal filter.

## Files to change

| File | Change |
|---|---|
| `web/src/components/model/types.ts` | Add `input_modalities?: string[]` to `CustomModelEntry` and `CustomModelFormState` |
| `web/src/pages/Setup/steps/ConnectStep.tsx` | Add capability toggle chips to custom model form |
| `src/server/app/users.py` | Validate `input_modalities` in custom models validation block |
| `src/llms/llm.py` | Add `custom_modalities` parameter to `get_input_modalities()` |
| `src/server/handlers/chat/ptc_workflow.py` | Look up custom modalities, pass to `get_input_modalities()` |
| `src/server/handlers/chat/flash_workflow.py` | Same as ptc_workflow |

## Out of scope

- Auto-detection of model capabilities from provider APIs (future enhancement)
- `video` modality for custom models
- Exposing `input_modalities` in the `/api/v1/models` response metadata
- Modality display in model selector UI (badges etc.)
