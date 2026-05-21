"""Catalog modifier landscape report.

Read-only. Pulls the live Square catalog and cross-references every modifier
against the recipe engine's modifier structures, so you can see at a glance:

- which modifier lists exist, how many items use them, and which are orphaned
- which modifiers are duplicated by name (the same option living in >1 list)
- what each modifier *means* to the recipe engine (sugar multiplier, ingredient
  addition, topping, foam, recipe override) or whether it's unmapped (e.g. a
  sticker the engine intentionally ignores)

Primary use: run against any merchant's catalog during onboarding to size the
modifier-mapping work before building a binding.

Usage:
    ./.venv/bin/python -m scripts.modifier_report
"""

from collections import defaultdict

from square.core.api_error import ApiError

from app.client import create_square_client
from app.order_inventory_projection import load_recipe_map


def _modifier_roles(modifier_id, recipe_map):
    """Return the recipe-engine roles a modifier ID plays (empty = unmapped)."""
    pkg = recipe_map.get("default_packaging_config", {}) or {}
    sugar = recipe_map.get("sugar_modifier_multipliers", {}) or {}
    additions = recipe_map.get("modifier_additions", {}) or {}
    topping_ids = set(pkg.get("topping_modifier_ids", []))
    hot_topping_ids = set(pkg.get("hot_allowed_topping_modifier_ids", []))
    foam_ids = set(pkg.get("cream_foam_modifier_ids", []))

    override_ids = set()
    for recipe in (recipe_map.get("sold_variation_recipes", {}) or {}).values():
        override_ids.update((recipe.get("modifier_overrides", {}) or {}).keys())

    roles = []
    if modifier_id in sugar:
        roles.append(f"sugar x{sugar[modifier_id]}")
    if modifier_id in additions:
        roles.append("ingredient")
    if modifier_id in topping_ids:
        roles.append("topping")
    if modifier_id in hot_topping_ids:
        roles.append("hot-topping")
    if modifier_id in foam_ids:
        roles.append("foam")
    if modifier_id in override_ids:
        roles.append("recipe-override")
    return roles


def _load_catalog(client):
    modifier_lists = {}
    for ml in client.catalog.list(types="MODIFIER_LIST"):
        data = getattr(ml, "modifier_list_data", None)
        modifier_lists[ml.id] = {
            "name": getattr(data, "name", None),
            "selection_type": getattr(data, "selection_type", None),
            "modifier_count": len(getattr(data, "modifiers", None) or []),
            "item_count": 0,
        }

    modifiers = []
    for m in client.catalog.list(types="MODIFIER"):
        data = getattr(m, "modifier_data", None)
        modifiers.append(
            {
                "id": m.id,
                "name": getattr(data, "name", None),
                "modifier_list_id": getattr(data, "modifier_list_id", None),
            }
        )

    for item in client.catalog.list(types="ITEM"):
        data = getattr(item, "item_data", None)
        for info in (getattr(data, "modifier_list_info", None) or []):
            mlid = getattr(info, "modifier_list_id", None)
            if mlid in modifier_lists:
                modifier_lists[mlid]["item_count"] += 1

    return modifier_lists, modifiers


def build_report(modifier_lists, modifiers, recipe_map):
    by_name = defaultdict(list)
    for m in modifiers:
        by_name[m["name"]].append(m)

    list_rows = []
    for mlid, ml in sorted(modifier_lists.items(), key=lambda kv: (kv[1]["name"] or "", kv[0])):
        list_rows.append(
            {
                "id": mlid,
                "name": ml["name"],
                "selection_type": ml["selection_type"],
                "modifier_count": ml["modifier_count"],
                "item_count": ml["item_count"],
                "orphaned": ml["item_count"] == 0,
            }
        )

    name_rows = []
    for name, entries in sorted(by_name.items()):
        instances = [
            {
                "id": e["id"],
                "list": modifier_lists.get(e["modifier_list_id"], {}).get("name")
                or e["modifier_list_id"],
                "roles": _modifier_roles(e["id"], recipe_map),
            }
            for e in entries
        ]
        mapped = any(inst["roles"] for inst in instances)
        name_rows.append(
            {
                "name": name,
                "instance_count": len(instances),
                "duplicated": len(instances) > 1,
                "mapped": mapped,
                "instances": instances,
            }
        )

    summary = {
        "modifier_list_count": len(modifier_lists),
        "orphaned_list_count": sum(1 for r in list_rows if r["orphaned"]),
        "distinct_modifier_names": len(by_name),
        "total_modifier_objects": len(modifiers),
        "duplicated_name_count": sum(1 for r in name_rows if r["duplicated"]),
        "unmapped_name_count": sum(1 for r in name_rows if not r["mapped"]),
    }
    return list_rows, name_rows, summary


def _print_report(list_rows, name_rows, summary):
    print("=" * 72)
    print("MODIFIER LISTS")
    print("=" * 72)
    for r in list_rows:
        flag = "  [ORPHANED — attached to 0 items]" if r["orphaned"] else ""
        print(f"{r['name']!r}  ({r['id']})")
        print(
            f"    modifiers={r['modifier_count']}  items={r['item_count']}"
            f"  selection={r['selection_type']}{flag}"
        )

    print()
    print("=" * 72)
    print("MODIFIERS BY NAME  (* = duplicated across lists)")
    print("=" * 72)
    for r in name_rows:
        dup = " *" if r["duplicated"] else ""
        status = "" if r["mapped"] else "   <unmapped — ignored by recipe engine>"
        print(f"{r['name']!r}  x{r['instance_count']}{dup}{status}")
        for inst in r["instances"]:
            roles = ", ".join(inst["roles"]) if inst["roles"] else "—"
            print(f"    {inst['id']}  list={inst['list']!r}  roles=[{roles}]")

    print()
    print("=" * 72)
    print("SUMMARY")
    print("=" * 72)
    for key, value in summary.items():
        print(f"  {key}: {value}")


def main():
    client = create_square_client()
    try:
        modifier_lists, modifiers = _load_catalog(client)
    except ApiError as error:
        print(f"Square API error: {error}")
        return 1

    recipe_map = load_recipe_map()
    list_rows, name_rows, summary = build_report(modifier_lists, modifiers, recipe_map)
    _print_report(list_rows, name_rows, summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
