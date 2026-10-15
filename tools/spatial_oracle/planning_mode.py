"""Small original planning-state corpus, consumed by the planning Rust owner.

This executes original instructions with supplied containers; it is not a
whole-game replay. Select VERA20K_GAMEMD_EXE, then run with --write or --check.
"""
import struct
from pathlib import Path

from tools import native_oracle as native

PATH = native.SCRATCH
NODES = PATH + 0x1000
ACTOR = PATH + 0x2000
EVENT = PATH + 0x3000
OUTPUT = PATH + 0x4000


def words(*values):
    return struct.pack("<" + "I" * len(values), *(v & 0xFFFFFFFF for v in values))


def signed(value):
    return struct.unpack("<i", words(value))[0]


def prestate(count, pending, loop_start=-1, loop_length=-1):
    writes = {PATH: words(ACTOR, 0x7EFE44, NODES, 8),
              PATH + 0x14: words(count), PATH + 0x8C: words(pending, loop_length, loop_start),
              NODES: words(*(PATH + 0x5000 + i * 0x100 for i in range(count)))}
    for i in range(count):
        node = PATH + 0x5000 + i * 0x100
        writes[node + 0x24] = words(PATH + 0x7000 + i * 0x100)
        writes[node + 0x30] = words(2)
        writes[node + 0xAC] = words(100 + i, 200 + i, 300 + i)
        writes[PATH + 0x7000 + i * 0x100] = words(PATH + 0x8000 + i * 0x100, PATH + 0x9000 + i * 0x100)
        writes[PATH + 0x8000 + i * 0x100 + 0x74] = words(400 + i)
        writes[PATH + 0x9000 + i * 0x100 + 0x74] = words(500 + i)
    return writes


def commit(count, pending, loop_start, loop_changed):
    writes = prestate(count, pending, loop_start, 3)
    writes[PATH + 0x98] = bytes([loop_changed])
    dumps = {"path": (PATH + 0x8C, 14)}
    for i in range(count):
        dumps[f"node{i}"] = (PATH + 0x5000 + i * 0x100 + 0xAC, 12)
        dumps[f"barrier{i}a"] = (PATH + 0x8000 + i * 0x100 + 0x74, 4)
        dumps[f"barrier{i}b"] = (PATH + 0x9000 + i * 0x100 + 0x74, 4)
    result = native.call(0x636CE0, ecx=PATH, writes=writes, dumps=dumps)
    path = bytes.fromhex(result["dumps"]["path"])
    rows = []
    for i in range(count):
        fields = struct.unpack("<3i", bytes.fromhex(result["dumps"][f"node{i}"]))
        rows.append(dict(index=i, active=fields[0], preserved=fields[1], cache=fields[2],
                         barrier_colors=[signed(int.from_bytes(bytes.fromhex(result["dumps"][f"barrier{i}{part}"]), "little")) for part in ("a", "b")]))
    return dict(count=count, pending=pending, loop_start=loop_start, loop_changed=loop_changed,
                after_pending=struct.unpack_from("<i", path)[0], after_loop_changed=path[12], nodes=rows)


def lookup(count, loop_start, loop_length, index):
    result = native.call(0x636E60, ecx=PATH, stack_args=[index & 0xFFFFFFFF],
                         writes=prestate(count, -1, loop_start, loop_length))
    pointer = result["eax"]
    return dict(count=count, loop_start=loop_start, loop_length=loop_length, index=index,
                node=None if pointer == 0 else (pointer - PATH - 0x5000) // 0x100)


def consume_loop(pending):
    writes = prestate(3, pending, 0, 3)
    for i in range(3):
        node = PATH + 0x5000 + i * 0x100
        record = PATH + 0xA000 + i * 0x100
        writes[node + 4] = words(PATH + 0xB000 + i * 0x100)
        writes[node + 0x10] = words(1)
        writes[node + 0x1C] = b"\x01"  # Already queued for native cleanup; no enqueue needed.
        writes[PATH + 0xB000 + i * 0x100] = words(record)
        writes[record] = words(ACTOR, EVENT + i * 0x100, -1, 0)
        writes[EVENT + i * 0x100] = bytes([0x40 + i]) * 0x6F
    result = native.call(0x636590, ecx=PATH, stack_args=[OUTPUT], writes=writes,
                         dumps={"nodes": (NODES, 12), "path": (PATH + 0x8C, 14),
                                "event": (OUTPUT, 0x6F), "retained_event": (PATH + 0x1D, 0x6F)})
    path = bytes.fromhex(result["dumps"]["path"])
    pointers = struct.unpack("<3I", bytes.fromhex(result["dumps"]["nodes"]))
    return dict(pending=pending, after_pending=struct.unpack_from("<i", path)[0],
                loop_start=struct.unpack_from("<i", path, 8)[0], rotated=bool(path[13]),
                nodes=[(pointer - PATH - 0x5000) // 0x100 for pointer in pointers],
                event=result["dumps"]["event"], retained_event=result["dumps"]["retained_event"])


def dispatch_latch(flag):
    writes = prestate(3, 1, 0, 3)
    writes[ACTOR + 0x514] = words(PATH)
    writes[PATH + 0x1C] = b"\x01"
    writes[EVENT + 0x1D] = bytes([flag])
    result = native.call(0x6386E0, ecx=ACTOR, edx=EVENT, writes=writes,
                         dumps={"path": (PATH + 0x8C, 14), "latch": (PATH + 0x1C, 1),
                                "count": (PATH + 0x14, 4)})
    path = bytes.fromhex(result["dumps"]["path"])
    return dict(flag=flag, count=int.from_bytes(bytes.fromhex(result["dumps"]["count"]), "little"),
                pending=struct.unpack_from("<i", path)[0], loop_start=struct.unpack_from("<i", path, 8)[0],
                executing=bool(int(result["dumps"]["latch"], 16)))


def patrol_conversion(loop_start, capabilities, missions):
    """639CB0 mutates all event memberships, gated by first-node actors."""
    writes = prestate(len(missions), -1, loop_start, len(missions) - loop_start)
    writes[ACTOR + 0x514] = words(PATH)
    dumps = {}
    for member, capable in enumerate(capabilities):
        actor = ACTOR + member * 0x800
        vtable = PATH + 0xC000 + member * 0x800
        stub = PATH + 0xF000 + member * 0x10
        writes[actor] = words(vtable)
        writes[vtable + 0x4C0] = words(stub)
        writes[stub] = b"\xb8" + words(int(capable)) + b"\xc3"
    for i, row in enumerate(missions):
        node = PATH + 0x5000 + i * 0x100
        members = PATH + 0xB000 + i * 0x100
        writes[node + 4] = words(members)
        writes[node + 0x10] = words(len(row))
        for member, mission in enumerate(row):
            record = PATH + 0x6000 + i * 0x400 + member * 0x100
            event = record + 0x40
            writes[members + member * 4] = words(record)
            writes[record] = words(ACTOR + member * 0x800, event)
            writes[event] = bytes([0xA5]) * 0x6F
            writes[event + 0xC] = bytes([mission])
            dumps[f"event{i}_{member}"] = (event, 0x6F)
    result = native.call(0x639CB0, ecx=ACTOR, writes=writes, dumps=dumps,
                         required_addresses=[0x639D13, 0x639D97] if any(capabilities) else [0x639D13])
    after = []
    for i, row in enumerate(missions):
        converted = []
        for member, mission in enumerate(row):
            event = bytes.fromhex(result["dumps"][f"event{i}_{member}"])
            assert event[:0xC] + event[0xD:] == bytes([0xA5]) * 0x6E
            converted.append(event[0xC])
        after.append(converted)
    return dict(loop_start=loop_start, capabilities=capabilities, missions=missions, after=after)


def commit_admission(mission, target_kind):
    vtable, target, target_vtable = PATH + 0xC000, PATH + 0xD000, PATH + 0xD400
    mission_stub, kind_stub, id_stub = PATH + 0xF000, PATH + 0xF010, PATH + 0xF020
    writes = {ACTOR: words(vtable), vtable + 0x184: words(mission_stub),
              mission_stub: b"\xb8" + words(mission) + b"\xc3",
              ACTOR + 0x2B4: words(0 if target_kind == "none" else target),
              target: words(target_vtable, target_vtable + 0x100),
              target_vtable + 0x2C: words(kind_stub),
              target_vtable + 0x110: words(id_stub),
              kind_stub: b"\xb8" + words(11 if target_kind == "cell" else 3) + b"\xc3",
              id_stub: b"\xb8" + words(17) + b"\xc2\x04\x00",
              target + 0x24: struct.pack("<2h", 10, 12)}
    result = native.call(0x638C70, ecx=ACTOR, writes=writes)
    return dict(mission=mission, target_kind=target_kind, admit=bool(result["eax"] & 255))


def interpolate_rgb(source, target, amount):
    result = native.call(0x6612C0, ecx=PATH, stack_args=[amount, PATH + 16],
                         writes={PATH: bytes(source), PATH + 16: bytes(target)},
                         dumps={"rgb": (PATH, 3)},
                         required_addresses=[0x6612C0, 0x6612ED, 0x66133A])
    return dict(source=source, target=target, amount=amount,
                rgb=list(bytes.fromhex(result["dumps"]["rgb"])))


def stroke_controls():
    """Execute both native width wrappers on the existing memory surface."""
    from unicorn import UC_HOOK_CODE
    from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_EDX, UC_X86_REG_ESP
    from tools.procedural_drawing_oracle import rally

    rows = []
    for start, end in [([20, 30], [120, 30]), ([40, 20], [40, 100]),
                       ([20, 20], [100, 100]), ([120, 30], [25, 85])]:
        for width, ms, selected in [(4, 0, True), (4, 32, True), (3, 198, True), (4, 242, False)]:
            f = rally.Rally({})
            u = f.u
            u.mem_write(0x88731C, words(rally.SURFACE))
            #72AD20 subtracts the168px sidebar and32px command bar even
            # with A8EB7C set. Supply the shell extent so marker/badge
            # clipping has the same160x120 tactical extent as the strokes.
            u.mem_write(0x886FB0, words(0, 0, rally.SIZE[0] + 168, rally.SIZE[1] + 32))
            u.mem_write(0xA8EB7C, b"\x01")
            clock = rally.MEM + 0x1FF000
            u.mem_write(0x7E1530, words(clock))

            def observe(vm, pc, _size, _data):
                if pc == clock:
                    sp = vm.reg_read(UC_X86_REG_ESP)
                    vm.reg_write(UC_X86_REG_EAX, ms)
                    vm.reg_write(UC_X86_REG_ESP, sp + 4)
                    from unicorn.x86_const import UC_X86_REG_EIP
                    vm.reg_write(UC_X86_REG_EIP, int.from_bytes(vm.mem_read(sp, 4), 'little'))

            u.hook_add(UC_HOOK_CODE, observe)
            outer = 0xFFFF if selected else 0
            u.reg_write(UC_X86_REG_EDX, outer)
            rally.call(u, 0x63D910, width, (*start, *end))
            u.reg_write(UC_X86_REG_EDX, 0x9F73)
            rally.call(u, 0x63D960, width, (*start, *end))
            # Original actor marker outer6x6, inset4x4. Node outer8x8
            # and inset6x6 are separately established by635350/635490.
            rally.call(u, 0x63D400, outer, end)
            rally.call(u, 0x63D480, 0x9F73, end)
            rows.append(dict(start=start, end=end, width=width, ms=ms,
                             selected=selected, inner_rgb565=0x9F73, pixels=f.pixels()))
    return rows


def generate():
    return dict(schema=1, commits=[commit(3, p, l, changed) for p, l, changed in
                                  [(-1, -1, False), (0, -1, False), (1, -1, False), (2, 0, True), (-1, 1, True)]],
                lookups=[lookup(3, l, length, i) for l, length in [(-1, -1), (0, 3), (1, 2)]
                         for i in [-1, 0, 1, 2, 3, 4, 6]],
                loop_consumes=[consume_loop(p) for p in [-1, 0, 2]],
                dispatch_latches=[dispatch_latch(flag) for flag in [1, 2]],
                patrol_conversions=[patrol_conversion(start, capabilities, missions) for start, capabilities, missions in [
                    (0, [True], [[2], [2], [2]]),
                    (1, [True], [[2], [2], [11], [29]]),
                    (1, [False, True], [[2, 2], [2, 11], [29, 2], [2, 2]]),
                    (0, [False, False], [[2, 2], [2, 11], [29, 2]]),
                ]],
                commit_admissions=[commit_admission(mission, target) for mission in [1, 2, 5, 11, 28]
                                   for target in ["none", "cell", "object"]],
                render=dict(stroke_controls=stroke_controls(), rgb_controls=[interpolate_rgb(source, target, amount)
                    for source, target, amount in [
                        ([1, 127, 255], [0, 0, 0], 80),
                        ([1, 127, 255], [255, 255, 255], 100),
                        ([255, 128, 1], [0, 0, 0], 80),
                        ([255, 128, 1], [255, 255, 255], 100),
                        ([17, 63, 249], [201, 3, 89], 80),
                        ([17, 63, 249], [201, 3, 89], 100),
                        ([17, 63, 249], [201, 3, 89], 356),
                    ]]))


if __name__ == "__main__":
    native.finish_vectors(generate, Path(__file__).with_suffix(".json"),
        provenance=lambda: native.provenance(
            scope="Five commits, 21 path lookups, three loop-head consumptions, two event-dispatch latch controls, four patrol conversions, 15 commit mission/target admission controls, seven RGB controls and16 composed planning stroke/marker controls.",
            assumptions=["Supplied actor, path, node, display predecessor and event records; original constructors do not execute.",
                         "Loop consumption uses three nodes with existing cleanup latches, enough vector capacity and loop start zero; nonloop destruction and whole-game scheduling are not covered."],
            substitutions=["Commit admission uses supplied actor mission, target class and target identity virtual getters; original 638C70 and target-token construction execute unchanged.",
                           "Patrol conversion executes original639CB0 with supplied path/memberships and Can_Attack_Move virtual return values. All event bytes other than the mission are checked unchanged; local feedback latch and whole-game scheduling are outside coverage.",
                           "Stroke controls reuse Rally's BSurface locking/storage with original7BA8C0 patterned and7BA610 solid pixels. Imported clock returns the supplied ms;63D910/63D960 and63D400/63D480 execute unchanged. Width/selection/endpoints are supplied, not whole-manager admission."],
            entry_points={"commit": 0x636CE0, "lookup": 0x636E60, "consume": 0x636590, "dispatch_latch": 0x6386E0, "patrol_conversion": 0x639CB0, "commit_admission": 0x638C70, "interpolate_rgb": 0x6612C0}),
        source_paths={"planning_mode": Path(__file__), "native_oracle": Path(native.__file__)})
