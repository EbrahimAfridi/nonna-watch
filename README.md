# Nonna Watch

Course project, Mobile Computing. Old Android phones listen for trouble in an older person's
home; a laptop in the house runs the AI and discards the audio; only text labels and alerts reach
Firebase; the family is alerted within seconds.

Start with [CONTEXT.md](CONTEXT.md). It holds the decisions, the plan, the team split and the
rules. The full requirements are in [docs/project-requirements.pdf](docs/project-requirements.pdf).

## Layout

```
hub/           Python hub (edge AI): YAMNet, VAD, Whisper, rules, Firestore sync
android/       Kotlin: :listener, :family, :core
cloud/         Firebase functions, seed scripts, Terraform
experiments/   harness scripts, CSV results, charts
docs/          requirements, API contract, schema
```

## Running each part

Each folder gets its own README as the part is built. Target: a teammate can clone and have that
part running in 15 minutes.

- Hub: [hub/README.md](hub/README.md)
- Android: [android/README.md](android/README.md)
- Cloud: [cloud/README.md](cloud/README.md)
- Experiments: [experiments/README.md](experiments/README.md)
