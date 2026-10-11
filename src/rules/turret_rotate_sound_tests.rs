//! TechnoType `TurretRotateSound` reader (`TechnoTypeClass::ReadINI @
//! 0x007133BA` through `VocClass::FindIndex @ 0x007514D0`) and its fixed
//! SOUNDMD binding through the production process owner, plus the two stock
//! authors read from the extracted retail INIs.
//!
//! `save`/`SinkingSound`'s siblings own the same reader shape; this file adds
//! only the key this mechanism consumes.

use std::sync::Arc;

use super::NativeRulesProcessOwner;
use super::NativeScenarioRulesPrefix;
use crate::rules::ini_parser::IniFile;
use crate::rules::ruleset::RuleSet;
use crate::rules::sound_ini::SoundRegistry;

/// The stock catalog shape: `[SoundList]` registers each id and
/// `VocClass::ReadINI` then reads the section named by that value.
fn catalog() -> Arc<SoundRegistry> {
    Arc::new(SoundRegistry::from_ini(&IniFile::from_str(
        "[SoundList]\n0=GrandCannonRotate\n1=YuriBustRotate\n2=WrongSection\n\
         [GrandCannonRotate]\nSounds=bgralo1\nControl=loop random all decay attack\n\
         Range=20\nVolume=30\n\
         [YuriBustRotate]\nSounds=byublo1a\nControl=loop random all decay attack\n\
         Range=20\nVolume=70\n\
         [WrongSection]\nSounds=bgralo1\n",
    )))
}

fn load(owner: &mut NativeRulesProcessOwner, mode: Option<&IniFile>, map: &IniFile) -> RuleSet {
    owner
        .load_scenario(NativeScenarioRulesPrefix::NonCampaign(mode), map)
        .unwrap()
        .into_parts()
        .0
}

/// The four processed passes (root, LANG, mode, map) through the process owner:
/// a missing, empty or unregistered name keeps the resolved id of the pass
/// before it, `ReadString` trims its copy, the catalog lookup folds case, and
/// the key compare does not.
#[test]
fn turret_rotate_sound_keeps_valid_prior_ids_across_every_layer() {
    let ini = IniFile::from_str;
    let root = ini("[BuildingTypes]\n0=GTGCAN\n[GTGCAN]\nTurret=yes\nROT=1\n\
         TurretRotateSound=GrandCannonRotate\n\
         [VehicleTypes]\n0=MTNK\n[MTNK]\nTurret=yes\nROT=5\n\
         TurretRotateSound=GrandCannonRotate\n\
         [AudioVisual]\nTurretRotateSound=WrongSection\n\
         [General]\nTurretRotateSound=WrongSection\n");
    // Unregistered and empty both retain the root's resolved id.
    let lang = ini("[GTGCAN]\nTurretRotateSound=Unknown\n[MTNK]\nTurretRotateSound=\n");
    // The copy is trimmed and the section-name lookup is case-insensitive.
    let mode = ini("[GTGCAN]\nTurretRotateSound=  yUrIbUsTrOtAtE  \n");
    // The key compare is exact-case: this line is a different key, so the
    // mode's value survives it.
    let map = ini("[GTGCAN]\nturretrotatesound=GrandCannonRotate\n[MTNK]\nTurretRotateSound=\n");

    let catalog = catalog();
    let mut owner = NativeRulesProcessOwner::from_cold_start_sources(
        root,
        Some(lang),
        ini(""),
        Arc::clone(&catalog),
    )
    .unwrap();
    assert!(Arc::ptr_eq(owner.fixed_sounds(), &catalog));
    let rules = load(&mut owner, Some(&mode), &map);

    assert_eq!(
        rules
            .object("GTGCAN")
            .unwrap()
            .turret_rotate_sound
            .as_deref(),
        Some("YuriBustRotate")
    );
    // `TechnoTypeClass` reads the key, not `BuildingTypeClass`: a vehicle binds
    // it, and no layer resolved a later name for it.
    assert_eq!(
        rules.object("MTNK").unwrap().turret_rotate_sound.as_deref(),
        Some("GrandCannonRotate")
    );
    // Neither layer's `[AudioVisual]`/`[General]` entry is a reader for it.
    assert!(
        rules
            .all_objects()
            .all(|object| object.turret_rotate_sound.as_deref() != Some("WrongSection"))
    );
}

/// The constructor's `-1` sentinel: no pass resolving a name leaves the field
/// empty, and an empty catalog resolves nothing.
#[test]
fn an_unresolved_key_stays_at_the_constructor_sentinel() {
    let ini = IniFile::from_str;
    let catalog = catalog();
    for silent in [
        "",
        "TurretRotateSound=\n",
        "TurretRotateSound=NotRegistered\n",
    ] {
        let root = ini(&format!(
            "[BuildingTypes]\n0=GTGCAN\n[GTGCAN]\nTurret=yes\nROT=1\n{silent}"
        ));
        let mut owner = NativeRulesProcessOwner::from_cold_start_sources(
            root,
            None,
            ini(""),
            Arc::clone(&catalog),
        )
        .unwrap();
        let rules = load(&mut owner, None, &ini(""));
        assert_eq!(
            rules.object("GTGCAN").unwrap().turret_rotate_sound,
            None,
            "{silent:?}"
        );
    }

    let root = ini("[BuildingTypes]\n0=GTGCAN\n[GTGCAN]\nTurret=yes\nROT=1\n\
         TurretRotateSound=GrandCannonRotate\n");
    let mut owner =
        NativeRulesProcessOwner::from_cold_start_sources(root, None, ini(""), Arc::default())
            .unwrap();
    let rules = load(&mut owner, None, &ini(""));
    assert!(
        rules
            .object("GTGCAN")
            .unwrap()
            .turret_rotate_sound
            .is_none()
    );
}

/// The active-YR values, read from the extracted retail INIs by the same
/// process owner: `[GTGCAN]` and `[CAEAST02]` are the only authors.
#[test]
fn retail_names_its_two_rotation_sounds() {
    let (Some(rules_ini), Some(art_ini), Some(sound_ini)) = (
        crate::rules::retail_ini_fixture::retail_ini("rulesmd.ini"),
        crate::rules::retail_ini_fixture::retail_ini("artmd.ini"),
        crate::rules::retail_ini_fixture::retail_ini("soundmd.ini"),
    ) else {
        return;
    };
    let mut owner = NativeRulesProcessOwner::from_cold_start_sources(
        rules_ini,
        None,
        art_ini,
        Arc::new(SoundRegistry::from_ini(&sound_ini)),
    )
    .unwrap();
    let rules = load(&mut owner, None, &IniFile::empty());

    let authors: Vec<(&str, bool, Option<&str>)> = ["GTGCAN", "CAEAST02", "MTNK", "GAPOWR"]
        .into_iter()
        .map(|name| {
            let object = rules.object(name).unwrap();
            (
                name,
                object.has_turret,
                object.turret_rotate_sound.as_deref(),
            )
        })
        .collect();
    assert_eq!(
        authors,
        [
            ("GTGCAN", true, Some("GrandCannonRotate")),
            ("CAEAST02", true, Some("YuriBustRotate")),
            // A turreted vehicle authors no rotation cue.
            ("MTNK", true, None),
            ("GAPOWR", false, None),
        ]
    );
    // No other stock type names the key, so the two above are the whole family.
    let mut naming = rules
        .all_objects()
        .filter(|object| object.turret_rotate_sound.is_some())
        .map(|object| object.id.as_str())
        .collect::<Vec<_>>();
    naming.sort_unstable();
    assert_eq!(naming, ["CAEAST02", "GTGCAN"]);
}
