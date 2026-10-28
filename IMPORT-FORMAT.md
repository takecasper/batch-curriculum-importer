# One45 Curriculum Schedule Import Format

The One45 schedule importer takes a fixed 19-column layout. `portfolio` is not one of them: the Wrangler reads it for routing and never writes it, because the importer picks the Portfolio at import time.

The Wrangler writes these headers in this order, from `CANONICAL_HEADERS` in `wrangler.py`. The header strings are exact, including the lowercase `email` and the trailing spaces on `Facilitator email ` and `Facilitator Role `.

## Columns

| # | Header | Required | Importer constraint | Wrangler handling |
| :--- | :--- | :--- | :--- | :--- |
| 1 | `Course Name` | Mandatory | Matches an existing Course name in the target Portfolio exactly; no match creates a new Course. | Always kept. |
| 2 | `Course Number` | Optional | Course catalog or ID code. | |
| 3 | `Subcourse Name` | Optional | Direct child of the Course (block, module, week). | |
| 4 | `Subcourse Number` | Optional | ID code for the Subcourse. | |
| 5 | `Session Type` | Mandatory | Must match an active entry in One45's Activity Type or Assessment Methods lists verbatim. | Not checked. |
| 6 | `Session Formative/Summative` | Mandatory | Exactly `Formative` or `Summative`, title case. Other casing breaks downstream CIR/AAMC exports. | Any casing or padding of `formative`/`summative` becomes `Formative`/`Summative`, logged as `Formative/Summative fixed`. Other values pass through. |
| 7 | `Session Name` | Mandatory | Name of the activity within the Course. | |
| 8 | `Section Name` | Mandatory | The scheduled instance of a Session. | |
| 9 | `Section Date` | Mandatory | Excel date cell, or text `YYYYMMDD`. Hyphens and slashes are rejected. | Readable dates become date cells shown as `yyyymmdd`. |
| 10 | `Start Time` | Mandatory | Start of the Section (`9:00 AM`, `14:00`, or an Excel time). | Readable times become time cells shown as `hh:mm`. |
| 11 | `End Time` | Mandatory | Must be after Start Time on the same row. | Normalized like Start Time; flagged red when not after Start Time. |
| 12 | `Location` | Mandatory | Must match an existing Room under Curriculum Management Tool > Buildings. The importer cannot create locations. | Not checked. |
| 13 | `Learner Group Family` | Contextual | Parent student group; must match an existing Group Family. | Not checked. |
| 14 | `Learner Group In` | Contextual | Cohort or subgroup within the family; must match an existing Learner Group. | Not checked. |
| 15 | `Learner Role` | Contextual | Curriculum role for the group; must match an existing role. | Not checked. |
| 16 | `Facilitator Last Name` | Optional | For human auditing; matching uses email. | |
| 17 | `Facilitator First Name` | Optional | | |
| 18 | `Facilitator email ` | Optional | Primary match key; must match an active One45 user's email. | Not checked. |
| 19 | `Facilitator Role ` | Contextual | Required when a Facilitator is assigned; must match a configured facilitator role. | Not checked. |

When scheduling for students, all three Learner Group columns must be filled and valid together.

## Importer rules

- **Column order:** keep the exact native order. Optional columns stay, with headers, even when blank. The Wrangler adds any missing column blank and logs it (`Column added (blank)`).
- **Existing entities:** Locations, Learner Groups, Roles, Activity Types and user accounts must already exist in One45. The importer rejects rows that reference anything unconfigured. The Wrangler has no access to One45 and cannot check these.
