# Team Beta — kiting strategy: keep distance, fire when the enemy is in
# range but retreat if they get too close.

def decide(friendly, enemies, api):
    target = api["find_nearest"](enemies)
    if target is None:
        api["hold_position"]()
        return

    dist = api["distance_to"](target)

    if dist <= 10.0 and friendly["attack_ready"]:
        api["attack"](target)
        api["log"]("returning fire on", target["name"])

    if dist < 6.0:
        flee_x = friendly["x"] - (target["x"] - friendly["x"])
        flee_y = friendly["y"] - (target["y"] - friendly["y"])
        api["move_toward"](flee_x, flee_y)
    elif dist > 10.0:
        api["move_toward"](target["x"], target["y"])
