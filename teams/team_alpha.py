# Team Alpha — aggressive pursuit strategy
# Runs inside the sandbox: no imports, only the functions on `api`.

def decide(friendly, enemies, api):
    target = api["find_nearest"](enemies)
    if target is None:
        api["hold_position"]()
        return

    if friendly["attack_ready"] and api["distance_to"](target) <= 10.0:
        api["attack"](target)
        api["log"]("engaging", target["name"])
    else:
        api["move_toward"](target["x"], target["y"])
