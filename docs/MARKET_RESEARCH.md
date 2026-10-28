# Market research: tools for multi-account AWS access and operations

*Research date: 28 October 2026. Project status, versions and prices change often. Every claim links to its source, so re-check before quoting this document.*

## 1. Question

Is there already a product, open source or paid, that does what lzctl does?

1. logs in to AWS through a **SAML 2.0 IdP** from the command line,
2. for **many accounts at once** (landing zones, hub/spoke),
3. keeps an **account inventory** with tags for selection, and
4. **runs operations and reports across accounts** (inventory, Excel, future patching)?

## 2. Short answer

**Each piece exists separately, but no single tool combines all four for SAML users.** That is especially true for a free tool that small companies can adopt without a server.

- **SAML → CLI login** is well covered, led by **saml2aws**. Those tools focus on getting credentials and stop there.
- **Profile switching** (Granted, aws-vault, awsume) assumes the profiles already exist. It is strongest with **IAM Identity Center**, not external SAML.
- **Running commands across accounts** exists in **awsrun** (Fidelity), a capable but niche library with a small community.
- **Inventory** is covered by **Steampipe / CloudQuery** (free core, paid hosting), **AWS Resource Explorer** (free) and enterprise CSPMs (paid). None of them log you in.
- **Paid access platforms** (Teleport, StrongDM, ...) solve access at the organisation level, with servers, per-user pricing and sales calls.

lzctl's opportunity is the **integrated, free, single-binary-style workflow**: login → select by tag → operate/report, for teams that federate AWS through a SAML IdP.

## 3. Landscape

### 3.1 SAML / IdP → AWS CLI credentials (direct overlap with `lzctl login`)

| Product | License / price | Status (Oct 2026) | Strengths | Gaps vs lzctl |
| --- | --- | --- | --- | --- |
| **[saml2aws](https://github.com/Versent/saml2aws)** (Versent) | MIT, free | Latest release **v2.36.19, 13 Mar 2025** ([GitHub API](https://api.github.com/repos/Versent/saml2aws/releases/latest)), so activity has slowed | The most IdPs (Okta, ADFS, Ping, Entra, Keycloak, Duo, ...), single Go binary, de-facto standard | One account/role per run; no account inventory, tags or fan-out; no reports |
| **[gimme-aws-creds](https://pypi.org/project/gimme-aws-creds)** (Nike) | Apache-2.0, free | Still packaged (v2.8.2 on [Homebrew](https://formulae.brew.sh/formula/gimme-aws-creds)) | Good Okta support, many Okta apps | **Okta only**; no fan-out or inventory |
| **[Leapp](https://github.com/Noovolari/leapp)** (Noovolari) | MPL-2.0, free | Not archived, last push May 2026, ~1.8k stars ([GitHub API](https://api.github.com/repos/Noovolari/leapp)). Some adopters have moved away ([Cloud Posse marks it deprecated](https://docs.cloudposse.com/resources/legacy/fundamentals/leapp/)). | Desktop GUI + CLI, OS vault, many integration types | Desktop-centric; no fan-out or inventory |
| **[Atmos Auth](https://docs.cloudposse.com/layers/identity/atmos-auth/)** (Cloud Posse) | Part of Atmos (open source) | Active | Unifies SSO, SAML, OIDC, GitHub Actions in `atmos.yaml` ([SAML tutorial](https://docs.cloudposse.com/layers/identity/tutorials/aws-saml/)) | Tied to the Atmos/Terraform reference architecture; defaults to Identity Center |
| Vendor CLIs (okta-aws-cli, aws-azure-login, ...) | Mostly free | Varies | Official for one IdP | One IdP each; login only |

### 3.2 Profile switching and credential managers

| Product | License / price | Status (Oct 2026) | Strengths | Gaps vs lzctl |
| --- | --- | --- | --- | --- |
| **[Granted](https://github.com/fwdcloudsec/granted)** | MIT, free | **Donated to fwd:cloudsec** after [Common Fate wound down](https://www.commonfate.io/blog/winding-down). Latest release **v0.40.0, 20 Oct 2026** ([GitHub API](https://api.github.com/repos/fwdcloudsec/granted/releases/latest)) | Fast `assume`, browser console per profile, strong Identity Center support | Needs profiles to exist; no SAML IdP login of its own; no fan-out or inventory |
| **[aws-vault](https://github.com/ByteNess/aws-vault)** | MIT, free | Original 99designs project **abandoned**; [ByteNess fork](https://raw.githubusercontent.com/ByteNess/aws-vault/main/README.md) is the maintained one | Keeps long-lived keys in the OS keychain, MFA | Designed for IAM-user keys, not SAML; no fan-out |
| **[awsume](https://github.com/trek10inc/awsume)** (Trek10) | MIT, free | Last push seen Sep 2024 ([ecosyste.ms](https://awesome.ecosyste.ms/projects/github.com%2Ftrek10inc%2Fawsume)) | Simple role assumption, plugins | Low activity; switching only |
| **[aws-sso-cli](https://synfinatic.github.io/aws-sso-cli/)** (synfinatic) | Open source, free | Active | Great for **many accounts/roles in Identity Center** | Identity Center only, no external SAML ([source](https://synfinatic.github.io/aws-sso-cli/latest)) |
| **AWS CLI `aws sso login`** | Free (AWS) | Active | Official | Identity Center only; one profile at a time |

### 3.3 Running commands across many accounts

| Product | License / price | Status | Notes |
| --- | --- | --- | --- |
| **[awsrun](https://github.com/fidelity/awsrun)** (Fidelity) | Apache-2.0, free | Active (last push Sep 2026, ~80 stars, [GitHub API](https://api.github.com/repos/fidelity/awsrun)) | **Conceptually the closest.** It runs user-defined Python commands or the AWS CLI concurrently over accounts selected from metadata, with SAML and cross-account credential plug-ins ([docs](https://fidelity.github.io/awsrun)). It is a framework you assemble yourself: no account discovery, no Excel reports, no production gate, small community. |
| Shell scripts + AWS CLI | Free | n/a | What most teams actually do. Fragile, and every team writes their own. |
| AWS Systems Manager / StackSets | AWS pricing | n/a | Run documents and stacks across accounts, from the AWS side. Not a personal CLI workflow. |

### 3.4 Inventory and visibility

| Product | License / price | Notes |
| --- | --- | --- |
| **[Steampipe](https://steampipe.io)** (Turbot) | Free and open source; paid hosted **Turbot Pipes** | SQL over live cloud APIs, multi-account by connection config ([comparison](https://www.cloudquery.io/docs/cq_vs_others/steampipe)). Powerful, but you need SQL plus separate credential setup. |
| **[CloudQuery](https://www.cloudquery.io)** | Freemium (third-party listing: Team plan ~$500/month, [toolradar](https://toolradar.com/compare/steampipe-vs-cloudquery)); announced joining env zero | Syncs inventory into a database. Built for platform/data teams, not ad-hoc ticket work. |
| **[AWS Resource Explorer](https://aws.amazon.com/resourceexplorer/pricing)** | **No additional charge**; multi-account search since 2023 ([announcement](https://aws.amazon.com/about-aws/whats-new/2023/11/aws-resource-explorer-multi-account-resource-search/)) | Good search, but needs Organization-level setup and has limited export or report options. Config-based features are billed separately. |
| **AWS Config aggregator** | ~$0.003 per configuration item recorded ([source](https://www.cloudquery.io/blog/cloudquery-vs-cloud-asset-inventory-tools)) | Compliance-grade history; cost grows with resource count. |
| CSPM / CNAPP (Wiz, Orca, Prisma Cloud, ...) | Paid, enterprise contracts | Full visibility and security posture; out of reach for small companies and overkill for "what's in this account". |

### 3.5 Paid access-management platforms

| Product | Pricing | Notes |
| --- | --- | --- |
| **StrongDM** | Not public; third-party listings start around **$50 per user per month**, "contact sales" for tiers ([toolradar](https://toolradar.com/tools/strongdm/pricing), [Capterra](https://www.capterra.com/p/181859/strongDM/)) | Centralised access proxy and auditing. Needs deployment and contracts. |
| **Teleport** | Not public, "contact us" ([G2](https://www.g2.com/compare/strongdm-vs-teleport)) | Identity-aware access for servers, Kubernetes and AWS. Enterprise-grade, with infrastructure to run. |
| **Common Fate** (just-in-time access) | Was commercial | Company **winding down** ([announcement](https://www.commonfate.io/blog/winding-down)). Its open-source Granted lives on. |

## 4. Feature comparison

| Capability | lzctl | saml2aws | Granted | aws-vault | awsrun | Steampipe | Resource Explorer | Paid platforms |
| --- | :-: | :-: | :-: | :-: | :-: | :-: | :-: | :-: |
| SAML IdP login from CLI | ✅ | ✅ (most IdPs) | ❌ | ❌ | via plug-in | ❌ | ❌ | ✅ |
| Many accounts in one login | ✅ | ❌ | n/a | n/a | ✅ | n/a | n/a | ✅ |
| Hub → spoke chaining | ✅ | partial | via profiles | ✅ | ✅ | n/a | n/a | ✅ |
| Account inventory with tags / globs | ✅ | ❌ | ❌ | ❌ | ✅ (metadata) | connections | Org-based | ✅ |
| Discover accounts from the IdP | ✅ | ❌ | Identity Center only | ❌ | ❌ | ❌ | Org-based | ✅ |
| Fan-out commands | ✅ | ❌ | ❌ | ❌ | ✅ | SQL | ❌ | partial |
| Resource inventory reports (Excel) | ✅ | ❌ | ❌ | ❌ | DIY | export via SQL | limited | varies |
| Production safety gate | ✅ | ❌ | ❌ | ❌ | ❌ | n/a | n/a | ✅ (policy) |
| Plugin system | ✅ | ❌ | partial | ❌ | ✅ | ✅ (plugins) | ❌ | n/a |
| Linux / macOS / Windows | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ (Windows via WSL) | web | ✅ |
| No server, free | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ (core) | ✅ | ❌ |

*"Partial" and "n/a" are judgements from public documentation. Corrections are welcome.*

## 5. Analysis

### 5.1 Gap that lzctl fills

Teams that federate AWS through a **SAML IdP** and manage **dozens of accounts** today combine saml2aws (login), hand-written `~/.aws/config` chaining profiles, and ad-hoc scripts or Steampipe for "what is running where". Nobody owns the glue. lzctl *is* that glue: one tool, one config, one mental model ("select accounts by tag, then act").

The second gap is **small and mid-size companies**. Paid platforms are priced per user and need servers. Enterprise inventory tools are overkill. A free CLI that produces an Excel report for a ticket in one command has no direct competitor.

### 5.2 SWOT

| | |
| --- | --- |
| **Strengths** | An integrated workflow (login + inventory + fan-out); tag-based selection; production safety; Excel reports for non-engineers; Python plugins; free and serverless |
| **Weaknesses** | Fewer IdPs than saml2aws (no Okta/Entra API yet); needs Python; new project with no community or track record yet; push MFA only through `manual` |
| **Opportunities** | saml2aws activity has slowed (no release since Mar 2025); Common Fate shut down; aws-vault's original was abandoned. Users are looking for maintained tools. Landing zones keep growing, and many companies still use SAML instead of Identity Center. |
| **Threats** | AWS pushes **IAM Identity Center**, which shrinks the SAML-only audience; Granted plus aws-sso-cli are strong for Identity Center; AWS could add native multi-account CLI features; the burden of maintaining IdP integrations |

### 5.3 Recommendations

1. **Don't compete on IdP count first.** Ship `manual` plus a browser-capture provider (AUTH-14) so *every* IdP works on day one, then add Okta and Entra API providers (AUTH-13).
2. **Support Identity Center as a provider (AUTH-15).** This turns the biggest threat into a feature: lzctl becomes the multi-account layer over *either* federation method.
3. **Lean into what nobody else does:** tag-based fan-out, Excel/CSV reports, the production gate, and safe write operations (patching).
4. **Interoperate, don't replace.** Write standard files, add `credential_process`, and make it easy to migrate from saml2aws configs and existing `~/.aws/config` profiles (already done).
5. **Make adoption effortless for small teams:** PyPI release, standalone binaries, `lzctl init` + `accounts discover` within 5 minutes.

## 6. Sources

- saml2aws: [repository](https://github.com/Versent/saml2aws), [latest release (API)](https://api.github.com/repos/Versent/saml2aws/releases/latest)
- Granted: [repository](https://github.com/fwdcloudsec/granted), [latest release (API)](https://api.github.com/repos/fwdcloudsec/granted/releases/latest), [v0.39.0 notes](https://newreleases.io/project/github/fwdcloudsec/granted/release/v0.39.0), [Common Fate winding down](https://www.commonfate.io/blog/winding-down)
- aws-vault: [ByteNess README](https://raw.githubusercontent.com/ByteNess/aws-vault/main/README.md), [ecosyste.ms](https://awesome.ecosyste.ms/projects/github.com%2Fbyteness%2Faws-vault), [99designs releases](https://www.github.com/99designs/aws-vault/releases)
- Leapp: [repository (API)](https://api.github.com/repos/Noovolari/leapp), [Cloud Posse note](https://docs.cloudposse.com/resources/legacy/fundamentals/leapp/)
- Atmos Auth: [docs](https://docs.cloudposse.com/layers/identity/atmos-auth/), [SAML tutorial](https://docs.cloudposse.com/layers/identity/tutorials/aws-saml/)
- gimme-aws-creds: [PyPI](https://pypi.org/project/gimme-aws-creds), [Homebrew](https://formulae.brew.sh/formula/gimme-aws-creds)
- awsume: [ecosyste.ms](https://awesome.ecosyste.ms/projects/github.com%2Ftrek10inc%2Fawsume)
- aws-sso-cli: [docs](https://synfinatic.github.io/aws-sso-cli/)
- awsrun: [docs](https://fidelity.github.io/awsrun), [PyPI](https://pypi.org/project/awsrun/), [repository (API)](https://api.github.com/repos/fidelity/awsrun)
- Steampipe / CloudQuery: [CloudQuery comparison](https://www.cloudquery.io/docs/cq_vs_others/steampipe), [toolradar comparison](https://toolradar.com/compare/steampipe-vs-cloudquery), [inventory tools article](https://www.cloudquery.io/blog/cloudquery-vs-cloud-asset-inventory-tools)
- AWS Resource Explorer: [pricing](https://aws.amazon.com/resourceexplorer/pricing), [multi-account announcement](https://aws.amazon.com/about-aws/whats-new/2023/11/aws-resource-explorer-multi-account-resource-search/)
- StrongDM / Teleport: [toolradar](https://toolradar.com/tools/strongdm/pricing), [Capterra](https://www.capterra.com/p/181859/strongDM/), [G2](https://www.g2.com/compare/strongdm-vs-teleport)
