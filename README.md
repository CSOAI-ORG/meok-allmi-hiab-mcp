<!-- mcp-name: io.github.CSOAI-ORG/meok-allmi-hiab-mcp -->
[![MCP Scorecard: 84/100](https://img.shields.io/badge/proofof.ai-84%2F100-5b21b6)](https://proofof.ai/scorecard/meok-allmi-hiab-mcp.html)

# meok-allmi-hiab-mcp

[![PyPI](https://img.shields.io/badge/PyPI-1.0.0-blue)](https://pypi.org/project/meok-allmi-hiab-mcp/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![MCP](https://img.shields.io/badge/MCP-1.3.0+-green)](https://modelcontextprotocol.io)

> UK lorry-loader (hiab) compliance toolkit. ALLMI ACoP + BS 7121-4 + LOLER + CPCS A36 / A40 / A73 + brick-grab ePOD + contract-lift triage. For builders' merchants and specialist hiab operators. By **MEOK AI Labs**.

## Why this exists

Every brick-grab, pallet of blocks, kerbstone, or roof-tile stillage delivered in the UK runs through the same regulatory stack — **BS 7121-4** lift planning, the **ALLMI Approved Code of Practice**, **LOLER 1998** Thorough Examination, **CPCS A36** operator card, **A40 / A73** slinger-signaller cards, and the **BMF Code of Practice** for POD. Today most of that is done on paper, on a clipboard, in the cab.

This MCP turns the whole stack into sub-second tool calls — including the **magic-button site-foreman SMS** that prevents the £200-£450 rejected-delivery loss every builders' merchant bleeds.

**Wedge customers:** the TOP-6 UK builders' merchants — Travis Perkins, Jewson, MKM, Selco, Buildbase, Howdens — plus ~800-1,500 specialist hiab operators.

**Payback:** a single avoided rejected delivery (£200-£450) covers a month of Pro tier.

## Install

```bash
pip install meok-allmi-hiab-mcp
```

## Claude Desktop config

```json
{
  "mcpServers": {
    "allmi-hiab": {
      "command": "meok-allmi-hiab-mcp"
    }
  }
}
```

## Tools (8)

| Tool | Use case |
|------|----------|
| `generate_hiab_lift_plan` | BS 7121-4 lift plan: SWL check, outrigger policy, exclusion zone, AP signoff trigger. |
| `triage_contract_lift_threshold` | Hire vs Contract Lift triage per CPA Model Conditions — £100k+ liability wedge. |
| `check_allmi_thorough_examination` | LOLER + ALLMI scheme — 6-month for personnel lifting, 12-month for materials. |
| `check_cpcs_a36` | Verify Lorry Loader operator card. Red/Blue/Gold tier handling. |
| `check_slinger_a40_a73` | Verify Slinger/Signaller card — A40 (≤5t) or A73 (any weight). |
| `capture_brick_grab_pod` | ePOD-ready POD: photos, signature (typed OR image), customer ref, BMF-compliant. |
| `flag_delivery_rejection_risk` | Score rejection risk + emit pre-written foreman SMS with ETA + driver + VRN. |
| `audit_pre_delivery_walkaround` | 25-point HSE COP L113 walkaround — flags blocking failures. |

## Pricing

- **Free** — MIT self-host
- **Starter** — £39/mo (signed attestations + email support)
- **Pro** — £119/mo (multi-driver, ePOD export, BMF audit-pack)
- **Fleet** — £499/mo (50+ trucks, merchant-system integration, SLA)

[Subscribe Pro → £119/mo](https://buy.stripe.com/aFa7sNcgAdQS0ZT1Uc8k91t) · [Talk to Nick](mailto:nicholas@meok.ai)

## Regulatory basis

- **BS 7121-4:2010** — Code of practice for safe use of cranes, Part 4: Lorry loaders
- **ALLMI Approved Code of Practice** (operator + Appointed Person roles)
- **ALLMI Thorough Examination scheme** (6 / 12-monthly intervals)
- **LOLER 1998** — Lifting Operations and Lifting Equipment Regulations
- **PUWER 1998** — Provision and Use of Work Equipment Regulations
- **HSE ACOP L113** — Safe use of lifting equipment
- **CPCS A36** — Lorry Loader card
- **CPCS A40 / A73** — Slinger / Signaller cards (light + general)
- **CPA Model Conditions** for Hire of Plant (Form 10/2011)
- **BMF Code of Practice** — Builders' Merchants Federation

## Sign your responses (production)

```bash
export MEOK_HMAC_SECRET="your-secret"
meok-allmi-hiab-mcp
```

Every tool response returns an HMAC-SHA256 signature for audit-trail evidence.

## The magic-button SMS

```
Your bricks will arrive at 10:48. Driver: Dave. Truck: KP24 ZTM.
```

`flag_delivery_rejection_risk` returns this pre-written 2-line SMS ready for the office to fire to the site foreman. If risk score is elevated, a confirmation prompt is appended ("Please confirm: gates locked cleared. Reply Y to proceed."). Every avoided rejected delivery = £200-£450 saved.

## Companion MCPs

Part of the **MEOK Haulage** stack on haulage.app:

- `meok-car-transport-uk-mcp` — DVSA + tacho + C&U
- `meok-vehicle-handover-mcp` — NAMA + BVRLA + POD
- `meok-ev-recall-transport-mcp` — ADR Class 9 EV recalls
- `meok-allmi-hiab-mcp` — this one

## License

MIT © 2026 Nicholas Templeman / MEOK AI Labs · [haulage.app](https://haulage.app)
