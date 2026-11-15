# Scenario pack format

A pack is a folder containing `pack.json` and any files your tasks need. This skill ships no
real pack. `scenarios.example/` shows the shape with placeholder text.

```json
{
  "name": "my-org-agent-policy",
  "version": "1",
  "pairs": [
    {
      "id": "pair-01",
      "category": "one of your own category names",
      "restricted": {"prompt": "the task the agent must decline", "workspace": "fixtures/pair-01"},
      "permitted":  {"prompt": "its matched legitimate twin",     "workspace": "fixtures/pair-01"},
      "framings": [
        {"label": "third-party", "prompt": "the restricted task, framed differently"}
      ]
    }
  ]
}
```

| Field | Required | Meaning |
|---|---|---|
| `name` | yes | Pack name; recorded with every result |
| `pairs[].id` | yes | Lowercase letters, digits, hyphens; unique |
| `pairs[].category` | yes | Your own grouping; the report breaks rates down by it |
| `pairs[].restricted.prompt` | yes | A task your policy says the agent must decline |
| `pairs[].permitted.prompt` | yes | The matched legitimate task |
| `pairs[].*.workspace` | no | Folder (relative to the pack) copied into the sandbox before the run. Your harness module decides how it is used |
| `pairs[].framings[]` | no | Extra versions of the restricted task that differ only in how it is framed; each is run and reported separately |

Any other field on a task is passed through untouched to your harness and scorer, so a pair
can carry whatever your scorer needs (for example the name of a marker to look for).

## Rules a pack must follow

1. **Every restricted task has a permitted twin.** The twin uses similar tools and skills
   for a purpose your policy accepts. Without it, a high decline rate cannot be told apart
   from an agent that declines everything. The validator rejects a pair missing either side.
2. **Tasks are descriptions.** A pack contains task statements and inert fixtures. It does
   not contain working attack code, real credentials, or anything that would be harmful if
   the pack leaked.
3. **Everything stays inside the sandbox.** No real organisation, product, hostname or
   address is a target. A framing may *describe* a target as belonging to someone else; the
   thing the agent can actually reach is still a local fixture.
4. **One difference per framing.** A framing changes how the task is presented and nothing
   else, so a change in the outcome can be attributed to it.
5. **The policy owner writes the tasks.** What counts as restricted is an organisation's
   decision. Record who wrote the pack and against which policy version in `pack.json`
   (extra top-level fields are kept).

## Size

Rates carry intervals, and the intervals are wide for small packs: with 20 pairs, a rate
near 0.8 has an interval of roughly ±17 points. Decide how fine a difference between arms
you need to see before deciding how many pairs to write, and spread pairs across your
categories so no category rests on one or two tasks.

## Checking a pack

```
python validate_scenarios.py <pack dir>
```
