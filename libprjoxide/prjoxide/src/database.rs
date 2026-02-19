use itertools::Itertools;
use ron::ser::PrettyConfig;
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet, HashMap, HashSet};
use std::{env, fmt, fs};

use std::fs::File;
use std::io::prelude::*;
use std::path::Path;
use log::{debug, info, warn};

// Deserialization of 'devices.json'

macro_rules! emit_bit_change_error {
    // Expands to either `$crate::panic::panic_2015` or `$crate::panic::panic_2021`
    // depending on the edition of the caller.
    ($($arg:tt)*) => {
        /* compiler built-in */

        warn!($($arg)*);
        if env::var("PRJOXIDE_ALLOW_BIT_CHANGE").is_ok() {

        } else {
            return Err(format!($($arg)*));
        }
    };
}

#[derive(Deserialize)]
pub struct DevicesDatabase {
    pub families: BTreeMap<String, FamilyData>,
}

#[derive(Deserialize)]
pub struct FamilyData {
    pub devices: BTreeMap<String, DeviceData>,
}

#[derive(Deserialize, Clone)]
pub struct DeviceVariantData {
    pub idcode: u32,
}

#[derive(Deserialize, Clone)]
pub struct DeviceData {
    pub packages: Vec<String>,
    pub frames: usize,
    pub bits_per_frame: usize,
    pub pad_bits_after_frame: usize,
    pub pad_bits_before_frame: usize,
    pub frame_ecc_bits: usize,
    pub max_row: u32,
    pub max_col: u32,
    pub col_bias: u32,
    pub fuzz: bool,
    pub variants: BTreeMap<String, DeviceVariantData>,
    pub tap_frame_count: usize
}

// Deserialization of 'tilegrid.json'

#[derive(Deserialize)]
pub struct DeviceTilegrid {
    pub tiles: BTreeMap<String, TileData>,
}

#[derive(Deserialize, Clone)]
pub struct OverlayTiletype {
    // All of the overlays that combine to make this tiletype
    pub overlays: BTreeSet<String>
}

#[derive(Serialize, Deserialize)]
pub struct TileData {
    pub tiletype: String,
    pub x: u32,
    pub y: u32,
    pub start_bit: usize,
    pub start_frame: usize,
    pub bits: usize,
    pub frames: usize,
}

// Deserialization of 'baseaddr.json'

#[derive(Deserialize)]
pub struct DeviceBaseAddrs {
    pub regions: BTreeMap<String, DeviceAddrRegion>,
}

#[derive(Deserialize)]
pub struct DeviceAddrRegion {
    pub addr: u32,
    pub abits: u32,
}

// Global network structure data

#[derive(Deserialize, Serialize, Clone)]
pub struct GlobalBranchData {
    pub branch_col: usize,
    pub from_col: usize,
    pub tap_driver_col: usize,
    pub tap_side: String,
    pub to_col: usize,
}

#[derive(Deserialize, Serialize, Clone)]
pub struct GlobalSpineData {
    pub from_row: usize,
    pub spine_row: usize,
    pub to_row: usize,
}

#[derive(Deserialize, Serialize, Clone)]
pub struct GlobalHrowData {
    pub hrow_col: usize,
    pub spine_cols: Vec<usize>,
}

#[derive(Deserialize, Serialize, Clone)]
pub struct DeviceGlobalsData {
    pub branches: Vec<GlobalBranchData>,
    pub spines: Vec<GlobalSpineData>,
    pub hrows: Vec<GlobalHrowData>,
}

impl DeviceGlobalsData {
    pub fn is_branch_loc(&self, col: usize) -> Option<char> {
        self.branches
            .iter()
            .find(|b| b.branch_col == col)
            .map(|b| b.tap_side.chars().next().unwrap())
    }
    pub fn branch_sink_to_origin(&self, col: usize) -> Option<usize> {
        self.branches
            .iter()
            .find(|b| col >= b.from_col && col <= b.to_col)
            .map(|b| b.branch_col)
    }
    pub fn is_spine_loc(&self, x: usize, y: usize) -> bool {
        self.hrows.iter().any(|h| h.spine_cols.contains(&x))
            && self.spines.iter().any(|s| s.spine_row == y)
    }
    pub fn spine_sink_to_origin(&self, x: usize, y: usize) -> Option<(usize, usize)> {
        let spine_column = self.hrows.iter()
            .flat_map(|x|x.spine_cols.clone())
            .map(|c| (x.abs_diff(c), c))
            .sorted()
            .map(|x| x.1)
            .next();

        let spine_data =
            self.spines.iter()
                .find(|s| y >= s.from_row && y <= s.to_row);

        spine_data.zip(spine_column)
            .map(|(spine, spine_col)| (spine_col, spine.spine_row))
    }

    pub fn is_hrow_loc(&self, x: usize, y: usize) -> bool {
        self.hrows.iter().any(|h| h.hrow_col == x) && self.spines.iter().any(|s| s.spine_row == y)
    }
    pub fn hrow_sink_to_origin(&self, x: usize, y: usize) -> Option<(usize, usize)> {
        match self
            .hrows
            .iter()
            .find(|h| {
                h.spine_cols
                    .iter()
                    .any(|c| ((x as i32) - (*c as i32)).abs() < 3)
                    || (((x as i32) - (h.hrow_col as i32)).abs() < 3)
            })
            .map(|h| h.hrow_col)
        {
            None => None,
            Some(hrow_col) => self
                .spines
                .iter()
                .find(|s| ((y as i32) - (s.spine_row as i32)).abs() <= 3)
                .map(|s| (hrow_col, s.spine_row)),
        }
    }
}

// IO pad pin data
#[derive(Deserialize, Clone)]
pub struct PadData {
    pub bank: i32,
    pub dqs: Vec<i32>,
    pub func: Vec<String>,
    pub offset: i32,
    pub pins: Vec<String>,
    pub pio: i32,
    pub side: String,
    pub vref: i32,
}

#[derive(Deserialize, Clone)]
pub struct DeviceIOData {
    pub packages: Vec<String>,
    pub pads: Vec<PadData>
}

// Interconnect timing data
#[derive(Deserialize, Clone)]
pub struct PipClassDelay {
    pub base: (i32, i32),
}

#[derive(Deserialize, Clone)]
pub struct InterconnectTimingData {
    pub pip_classes: BTreeMap<String, PipClassDelay>,
}

// Cell timing data
#[derive(Deserialize, Clone)]
pub struct CellPropDelay {
    pub from_pin: String,
    pub to_pin: String,
    pub minv: i32,
    pub maxv: i32,
}

#[derive(Deserialize, Clone)]
pub struct CellSetupHold {
    pub clock: String,
    pub pin: String,
    pub min_setup: i32,
    pub max_setup: i32,
    pub min_hold: i32,
    pub max_hold: i32,
}

#[derive(Deserialize, Clone)]
pub struct CellTypeTiming {
    pub iopaths: Vec<CellPropDelay>,
    pub setupholds: Vec<CellSetupHold>,
}

#[derive(Deserialize, Clone)]
pub struct CellTimingData {
    pub celltypes: BTreeMap<String, CellTypeTiming>,
}

// Tile bit database structures

#[derive(Deserialize, Serialize, PartialEq, Eq, PartialOrd, Ord, Clone)]
pub struct ConfigBit {
    pub frame: usize,
    pub bit: usize,
    pub invert: bool,
}

impl fmt::Debug for ConfigBit {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            f,
            "{}F{}B{}",
            match self.invert {
                true => "!",
                false => "",
            },
            self.frame,
            self.bit
        )
    }
}

#[derive(Deserialize, Serialize, Clone, Ord, PartialOrd, Eq, PartialEq)]
pub struct ConfigPipData {
    pub from_wire: String,
    pub bits: BTreeSet<ConfigBit>,
}

#[derive(Deserialize, Serialize, Clone)]
pub struct ConfigWordData {
    pub bits: Vec<BTreeSet<ConfigBit>>,
    #[serde(default)]
    #[serde(skip_serializing_if = "String::is_empty")]
    pub desc: String,
}

#[derive(Deserialize, Serialize, Clone)]
pub struct ConfigEnumData {
    pub options: BTreeMap<String, BTreeSet<ConfigBit>>,
    #[serde(default)]
    #[serde(skip_serializing_if = "String::is_empty")]
    pub desc: String,
}

fn is_false(x: &bool) -> bool {
    !(*x)
}

#[derive(Deserialize, Serialize, Clone, Ord, PartialOrd, Eq, PartialEq)]
pub struct FixedConnectionData {
    pub from_wire: String,
    #[serde(default)]
    #[serde(skip_serializing_if = "is_false")]
    pub bidir: bool,
}

#[derive(Deserialize, Serialize, Clone)]
pub struct TileBitsDatabase {
    pub pips: BTreeMap<String, Vec<ConfigPipData>>,
    pub words: BTreeMap<String, ConfigWordData>,
    pub enums: BTreeMap<String, ConfigEnumData>,
    pub conns: BTreeMap<String, Vec<FixedConnectionData>>,
    #[serde(default)]
    #[serde(skip_serializing_if = "BTreeSet::is_empty")]
    pub always_on: BTreeSet<ConfigBit>,
    #[serde(default)]

    // Tiletype and relative offset for the tiles that this tiletype configures -- that is, changes in
    // this tiles bits reflect a change in either pips or primitives in the other tile.
    #[serde(skip_serializing_if = "BTreeSet::is_empty")]
    pub tile_configures_external_tiles : BTreeSet<(i32, i32)>,
}

impl TileBitsDatabase {
    pub fn get_source_wires(&self) -> BTreeSet<String> {
        let mut sources = BTreeSet::new();
        for pip in self.pips.values().flatten() {
            sources.insert(pip.from_wire.to_string());
        }
        for conn in self.conns.values().flatten() {
            sources.insert(conn.from_wire.to_string());
        }
        return sources;
    }

    pub fn get_sink_wires(&self) -> BTreeSet<String> {
        let mut sinks = BTreeSet::new();
        for pip_sink in self.pips.keys() {
            sinks.insert(pip_sink.to_string());
        }
        for conn_sink in self.conns.keys() {
            sinks.insert(conn_sink.to_string());
        }
        return sinks;
    }
}

pub struct TileBitsData {
    tiletype: String,
    pub db: TileBitsDatabase,
    dirty: bool,
    new_pips: u32,
    new_enums: u32,
    new_words: u32
}

impl TileBitsData {
    pub fn sort(&mut self) {
        self.db.conns.iter_mut().for_each(|(_,conn)| conn.sort());
        self.db.pips.iter_mut().for_each(|(_,pip)| pip.sort());
    }

    pub fn new(tiletype: &str, db: TileBitsDatabase) -> TileBitsData {
        TileBitsData {
            tiletype: tiletype.to_string(),
            db: db.clone(),
            dirty: false,
            new_pips: 0,
            new_enums: 0,
            new_words : 0
        }
    }

    pub fn merge_configs(&mut self, other_db: &TileBitsDatabase) -> Result<(), String> {
        for (word, word_config) in other_db.words.iter() {
            self.add_word(word, &*word_config.desc, word_config.bits.clone())?;
        };
        for (enm, enum_config) in other_db.enums.iter() {
            for (option, option_bits) in enum_config.options.iter() {
                self.add_enum_option(enm, option, &*enum_config.desc, option_bits.clone())?;
            }
        }

        for external_tile_configs in other_db.tile_configures_external_tiles.iter() {
            self.set_bel_offset(Some(external_tile_configs.clone()))?;
        }

        Ok(())
    }

    pub fn merge(&mut self, other_db: &TileBitsDatabase) -> Result<(), String> {
        debug!("Merging {}", self.tiletype);
        self.merge_configs(other_db)?;

        for (to, pip_data) in other_db.pips.iter() {
            for from in pip_data.iter() {
                self.add_pip(&from.from_wire, to, from.bits.clone())?;
            }
        }

        for (to, from_wires) in other_db.conns.iter() {
            for from in from_wires {
                self.add_conn(&*from.from_wire, &*to);
                if from.bidir {
                    self.add_conn(&*to, &*from.from_wire);
                }
            }
        }
        self.dirty = true;

        Ok(())
    }

    pub fn find_pip_data(&self,from: &str, to: &str) -> Option<&ConfigPipData> {
        for pip_config in self.db.pips.get(to)? {
            if pip_config.from_wire == from {
                return Some(pip_config);
            }
        }
        None
    }

    pub fn add_pip(&mut self, from: &str, to: &str, bits: BTreeSet<ConfigBit>) -> Result<(), String> {
        if !self.db.pips.contains_key(to) {
            debug!("Inserting new pip destination {to}");
            self.db.pips.insert(to.to_string(), Vec::new());
        }
        let ac = self.db.pips.get_mut(to).unwrap();
        for ad in ac.iter_mut() {
            if ad.from_wire == from {
                if bits != ad.bits {
                    emit_bit_change_error!(
                        "Bit conflict for {}. {}<-{} existing: {:?} new: {:?}",
                        self.tiletype, from, to, ad.bits, bits
                    );

                    ad.bits = bits;
                    self.dirty = true;
                    self.new_pips += 1;

                    return Ok(());
                }

                debug!("Pip {from} -> {to} already exists for {}", self.tiletype);
                return Ok(());
            }
        }
        self.dirty = true;
        self.new_pips += 1;

        debug!("Inserting new pip {from} -> {to} for {}", self.tiletype);
        ac.push(ConfigPipData {
            from_wire: from.to_string(),
            bits: bits.clone(),
        });

        Ok(())
    }
    pub fn add_word(&mut self, name: &str, desc: &str, bits: Vec<BTreeSet<ConfigBit>>) -> Result<(), String> {
        self.dirty = true;
        match self.db.words.get_mut(name) {
            None => {
                self.db.words.insert(
                    name.to_string(),
                    ConfigWordData {
                        desc: desc.to_string(),
                        bits: bits.clone(),
                    },
                );

                self.new_words += 1;
            }
            Some(word) => {
                if !desc.is_empty() && desc != &word.desc {
                    word.desc = desc.to_string();
                }
                if bits.len() != word.bits.len() {
                    emit_bit_change_error!(
                        "Width conflict {}.{} existing: {:?} new: {:?}",
                        self.tiletype,
                        name,
                        word.bits.len(),
                        bits.len()
                    );
                }
                for (bit, (e, n)) in word.bits.iter().zip(bits.iter()).enumerate() {
                    if e != n {
                        emit_bit_change_error!(
                            "Bit conflict for {}.{}[{}] existing: {:?} new: {:?}",
                            self.tiletype, name, bit, e, n
                        );
                    }
                }
            }
        }

        Ok(())
    }

    pub fn set_bel_offset(&mut self, bel_relative_location : Option<(i32, i32)>) -> Result<(), String> {
        if !self.db.tile_configures_external_tiles.is_empty() &&
            self.db.tile_configures_external_tiles.iter().next() != bel_relative_location.as_ref() {
            emit_bit_change_error!(
                "Bel offset conflict for {}. existing: {:?} new: {:?}",
                self.tiletype, self.db.tile_configures_external_tiles, bel_relative_location
            );
        }
        info!("Setting bel offset {} {:?}", self.tiletype, bel_relative_location);

        bel_relative_location.iter().for_each(
            |loc| { self.db.tile_configures_external_tiles.insert(loc.clone()); }
        );
        self.dirty = true;

        Ok(())
    }
    pub fn add_enum_option(
        &mut self,
        name: &str,
        option: &str,
        desc: &str,
        bits: BTreeSet<ConfigBit>
    ) -> Result<(), String> {
        if !self.db.enums.contains_key(name) {
            self.db.enums.insert(
                name.to_string(),
                ConfigEnumData {
                    options: BTreeMap::new(),
                    desc: desc.to_string(),
                },
            );
        }
        let ec = self.db.enums.get_mut(name).unwrap();
        if !desc.is_empty() && desc != &ec.desc {
            ec.desc = desc.to_string();
            self.new_enums += 1;
            self.dirty = true;
        }
        match ec.options.get_mut(option) {
            Some(old_bits) => {
                if bits != *old_bits {
                    emit_bit_change_error!(
                        "Bit conflict for {}.{}={} existing: {:?} new: {:?}",
                        self.tiletype, name, option, old_bits, bits
                    );

                    ec.options.insert(option.to_string(), bits);
                    self.new_enums += 1;
                    self.dirty = true;
                }
            }
            None => {
                ec.options.insert(option.to_string(), bits);
                self.new_enums += 1;
                self.dirty = true;
            }
        }

        Ok(())
    }
    pub fn add_conn(&mut self, from: &str, to: &str) {
        if !self.db.conns.contains_key(to) {
            self.db.conns.insert(to.to_string(), Vec::new());
        }
        let pc = self.db.conns.get_mut(to).unwrap();
        if pc.iter().any(|fc| fc.from_wire == from) {
            // Connection already exists
            debug!("Connection {from} -> {to} already exists {}", self.tiletype);
        } else {
            info!("Connection {from} -> {to} added {}", self.tiletype);
            self.dirty = true;
            pc.push(FixedConnectionData {
                from_wire: from.to_string(),
                bidir: false,
            });
        }
    }
    pub fn set_always_on(&mut self, aon: &BTreeSet<ConfigBit>) {
        if aon != &self.db.always_on {
            self.db.always_on = aon.clone();
            self.dirty = true;
        }
    }
}

type FamilyName = String;
type DeviceName = String;
type DeviceSpecifier = (FamilyName, DeviceName);
type TileName = String;

type TileTypeName = String;

pub struct Database {
    root: Option<String>,
    builtin: Option<include_dir::Dir<'static>>,
    devices: DevicesDatabase,
    tilegrids: HashMap<DeviceSpecifier, DeviceTilegrid>,
    baseaddrs: HashMap<DeviceSpecifier, DeviceBaseAddrs>,
    globals: HashMap<DeviceSpecifier, DeviceGlobalsData>,
    iodbs: HashMap<DeviceSpecifier, DeviceIOData>,
    interconn_tmg: HashMap<DeviceSpecifier, InterconnectTimingData>,
    cell_tmg: HashMap<DeviceSpecifier, CellTimingData>,

    tilebits: HashMap<(FamilyName, TileTypeName), TileBitsData>,
    ipbits: HashMap<(FamilyName, TileTypeName), TileBitsData>,

    overlay_based_devices:  HashSet<DeviceSpecifier>,
    _overlays: Option<HashMap<DeviceSpecifier, BTreeMap<TileTypeName, OverlayTiletype>>>,
    overlay_tiletypes: HashMap<DeviceSpecifier, BTreeMap<TileName, TileTypeName>>,
}

impl Database {
    pub fn new(root: &str) -> Database {
        let mut devices_json_buf = String::new();
        // read the whole file
        debug!("Opening database at {}", root);

        File::open(format!("{}/devices.json", root))
            .unwrap()
            .read_to_string(&mut devices_json_buf)
            .unwrap();

        let devices : DevicesDatabase = serde_json::from_str(&devices_json_buf).unwrap();
        let mut overlay_based_devices = HashSet::new();

        if !env::var("PRJOXIDE_DISABLE_OVERLAYS").is_ok() {
            for (family, family_data) in devices.families.iter() {
                for (device, _) in family_data.devices.iter() {
                    if Path::new(format!("{root}/{family}/{device}/overlays.json").as_str()).exists() {
                        overlay_based_devices.insert((family.clone(), device.clone()));
                    }
                }
            }
        }

        Database {
            root: Some(root.to_string()),
            builtin: None,
            devices: devices,
            tilegrids: HashMap::new(),
            baseaddrs: HashMap::new(),
            globals: HashMap::new(),
            iodbs: HashMap::new(),
            interconn_tmg: HashMap::new(),
            cell_tmg: HashMap::new(),
            tilebits: HashMap::new(),
            ipbits: HashMap::new(),
            overlay_based_devices,
            _overlays: None,
            overlay_tiletypes: HashMap::new(),
        }
    }
    pub fn new_builtin(data: include_dir::Dir<'static>) -> Database {
        let devices_json_buf = data.get_file("devices.json").unwrap().contents_utf8().unwrap();

        let devices : DevicesDatabase = serde_json::from_str(&devices_json_buf).unwrap();
        let mut overlay_based_devices = HashSet::new();
        for (family, family_data) in devices.families.iter() {
            for (device, _) in family_data.devices.iter() {
                if data.get_file(format!("{family}/{device}/overlays.json").as_str()).is_some() {
                    overlay_based_devices.insert((family.clone(), device.clone()));
                }
            }
        }

        Database {
            root: None,
            builtin: Some(data),
            devices: devices,
            tilegrids: HashMap::new(),
            baseaddrs: HashMap::new(),
            globals: HashMap::new(),
            iodbs: HashMap::new(),
            interconn_tmg: HashMap::new(),
            cell_tmg: HashMap::new(),
            tilebits: HashMap::new(),
            ipbits: HashMap::new(),
            overlay_based_devices,
            _overlays: None,
            overlay_tiletypes: HashMap::new(),
        }
    }
    // Check if a file exists
    pub fn file_exists(&self, path: &str) -> bool {
        match &self.root {
            Some(r) => {
                Path::new(&format!("{}/{}", r, path)).exists()
            }
            None => {
                self.builtin.unwrap().get_file(path).is_some()
            }
        }
    }
    // Get the content of a file
    pub fn read_file(&self, path: &str) -> String {
        match &self.root {
            Some(r) => {
                let mut buf = String::new();
                File::open(format!("{}/{}", r, path)).unwrap().read_to_string(&mut buf).unwrap();
                buf
            }
            None => {
                self.builtin.unwrap().get_file(path).unwrap().contents_utf8().unwrap().to_string()
            }
        }
    }
    // Both functions return a (family, name, data) 3-tuple
    pub fn device_by_name(&self, name: &str) -> Option<(String, String, DeviceData)> {
        for (f, fd) in self.devices.families.iter() {
            for (d, data) in fd.devices.iter() {
                if d == name {
                    return Some((f.to_string(), d.to_string(), data.clone()));
                }
            }
        }
        None
    }
    pub fn device_by_idcode(&self, idcode: u32) -> Option<(String, String, String, DeviceData)> {
        for (f, fd) in self.devices.families.iter() {
            for (d, data) in fd.devices.iter() {
                for (v, var_data) in data.variants.iter() {
                    if var_data.idcode == idcode {
                        return Some((f.to_string(), d.to_string(), v.to_string(), data.clone()));
                    }
                }
            }
        }
        None
    }


    pub fn device_overlay_tiletypes(&mut self, family: &str, device: &str) -> Result<&BTreeMap<TileName, TileTypeName>, String> {
        let key = (family.to_string(), device.to_string());
        if !self.overlay_tiletypes.contains_key(&key) {
            let json_buf = self.read_file(&format!("{}/{}/overlays.json", family, device));

            let root: BTreeMap<String, BTreeMap<String, BTreeSet<String>>> =
                serde_json::from_str(&json_buf)
                    .map_err(|e| format!("Failed to parse overlays.json: {}", e))?;

            let tiletypes = root.get("tiletypes")
                .ok_or("missing tiletypes")?;

            let tiletype_lookup = tiletypes.iter()
                .flat_map(|(k, set)| set.iter().map(move |v| (v.clone(), k.clone())))
                .try_fold(BTreeMap::new(), |mut acc, (v, k)| {
                    match acc.insert(v.clone(), k.clone()) {
                        None => Ok(acc),
                        Some(prev) => Err(format!(
                            "Collision: '{}' belongs to both '{}' and '{}'",
                            v, prev, k
                        )),
                    }
                })?;

            self.overlay_tiletypes.insert(key.clone(), tiletype_lookup);
        }
        self.overlay_tiletypes.get(&key).ok_or(format!("Could not find overlay tile types for {family} {device}"))
    }
    pub fn overlays(&mut self) -> &HashMap<DeviceSpecifier, BTreeMap<TileTypeName, OverlayTiletype>> {
        if self._overlays.is_none() {
            let mut overlays = HashMap::new();

            for (family, family_data) in self.devices.families.iter() {
                for (device, _) in family_data.devices.iter() {

                    if self.file_exists(&format!("{}/{}/overlays.json", family, device)) {
                        let json_buf = self.read_file(&format!("{}/{}/overlays.json", family, device));

                        let root: BTreeMap<String, BTreeMap<String, BTreeSet<String>>> =
                            serde_json::from_str(&json_buf)
                                .map_err(|e| format!("Failed to parse overlays.json: {}", e)).unwrap();

                        let overlay_tiletypes = root.get("overlays")
                            .ok_or(format!("missing overlays in {device}")).unwrap();

                        let device_overlays = overlay_tiletypes.iter().map(|(name, contents)| {
                            (name.clone(), OverlayTiletype {
                                overlays: contents.clone()
                            })
                        }).collect();

                        overlays.insert((family.clone(), device.clone()), device_overlays);
                    }
                }
            }

            self._overlays = Some(overlays);
        }

        &self._overlays.as_ref().unwrap()
    }
    pub fn device_tiletypes(&mut self, family: &str) -> BTreeSet<TileTypeName> {
        let mut tiletypes = BTreeSet::new();
        let root = self.root.clone().unwrap();
        let tiletypes_dir = format!("{}/{}/tiletypes/", root, family);

        match fs::read_dir(&tiletypes_dir) {
            Ok(entries) => {
                for entry in entries {
                    let file = entry.unwrap();
                    if file.path().extension().unwrap_or_default() == "ron" {
                        tiletypes.insert(file.path().file_stem().unwrap().to_str().unwrap().to_string());
                    }
                }
            }
            Err(e) => {
                debug!("Failed to read tile types for {family} {tiletypes_dir}: {e}");
            }
        }

        match fs::read_dir(format!("{}/{}/overlays/", root, family)) {
            Ok(entries) => {
                for entry in entries {
                    let file = entry.unwrap();
                    if file.path().extension().unwrap_or_default() == "ron" {
                        let overlay = file.path().file_stem().unwrap().to_str().unwrap().to_string();
                        tiletypes.insert(format!("overlays/{}", overlay));
                    }
                }
            }
            Err(e) => {
                debug!("Failed to read overlay tile types for {family}: {e}");
            }
        }

        debug!("Reading {} tile types {:?}", family, tiletypes);
        tiletypes
    }
    // Tilegrid for a device by family and name
    pub fn device_tilegrid(&mut self, family: &str, device: &str) -> &DeviceTilegrid {
        let key = (family.to_string(), device.to_string());
        if !self.tilegrids.contains_key(&key) {
            let tg_json_buf = self.read_file(&format!("{}/{}/tilegrid.json", family, device));
            let mut tg : DeviceTilegrid = serde_json::from_str(&tg_json_buf).unwrap();

            if self.overlay_based_devices.contains(&key) {

                let device_overlay = self.device_overlay_tiletypes(family, device).unwrap();
                for (tile, tile_data) in tg.tiles.iter_mut() {
                    if let Some(tile_type_name) = device_overlay.get(tile) {
                        tile_data.tiletype = tile_type_name.clone();
                    } else {
                        warn!("Could not find {tile} in overlays listing {device}");
                    }
                }
            }

            self.tilegrids.insert(key.clone(), tg);
        }
        self.tilegrids.get(&key).unwrap()
    }
    // IP region base addresses for a device by family and name
    pub fn device_baseaddrs(&mut self, family: &str, device: &str) -> &DeviceBaseAddrs {
        let key = (family.to_string(), device.to_string());
        if !self.baseaddrs.contains_key(&key) {
            let bs_json_buf = self.read_file(&format!("{}/{}/baseaddr.json", family, device));
            let bs = serde_json::from_str(&bs_json_buf).unwrap();
            self.baseaddrs.insert(key.clone(), bs);
        }
        self.baseaddrs.get(&key).unwrap()
    }
    // Global data for a device by family and name
    pub fn device_globals(&mut self, family: &str, device: &str) -> &DeviceGlobalsData {
        let key = (family.to_string(), device.to_string());
        if !self.globals.contains_key(&key) {
            let bs_json_buf = self.read_file(&format!("{}/{}/globals.json", family, device));
            let bs = serde_json::from_str(&bs_json_buf).unwrap();
            self.globals.insert(key.clone(), bs);
        }
        self.globals.get(&key).unwrap()
    }
    // IO data for a device by family and name
    pub fn device_iodb(&mut self, family: &str, device: &str) -> &DeviceIOData {
        let key = (family.to_string(), device.to_string());
        if !self.iodbs.contains_key(&key) {
            let io_json_buf = self.read_file(&format!("{}/{}/iodb.json", family, device));
            let io = serde_json::from_str(&io_json_buf).unwrap();
            self.iodbs.insert(key.clone(), io);
        }
        self.iodbs.get(&key).unwrap()
    }
    // Interconnect timing data by family and speed grade
    pub fn interconn_timing_db(&mut self, family: &str, grade: &str) -> &InterconnectTimingData {
        let key = (family.to_string(), grade.to_string());
        if !self.interconn_tmg.contains_key(&key) {
            let tmg_json_buf = self.read_file(&format!("{}/timing/interconnect_{}.json", family, grade));
            let tmg = serde_json::from_str(&tmg_json_buf).unwrap();
            self.interconn_tmg.insert(key.clone(), tmg);
        }
        self.interconn_tmg.get(&key).unwrap()
    }
    // Cell timing data by family and speed grade
    pub fn cell_timing_db(&mut self, family: &str, grade: &str) -> &CellTimingData {
        let key = (family.to_string(), grade.to_string());
        if !self.cell_tmg.contains_key(&key) {
            let tmg_json_buf = self.read_file(&format!("{}/timing/cells_{}.json", family, grade));
            let tmg = serde_json::from_str(&tmg_json_buf).unwrap();
            self.cell_tmg.insert(key.clone(), tmg);
        }
        self.cell_tmg.get(&key).unwrap()
    }
    pub fn merge(&mut self, other: &mut Database) -> Result<(), String>{
        let families : BTreeSet<String> = self.devices.families.iter().map(|(k,_v)| k.to_string()).collect();

        for family in families {
            let family_str = family.as_str();

            for tiletype in other.device_tiletypes(family_str) {
                let other_tiledb = other.tile_bitdb(family_str, tiletype.as_str());
                self.tile_bitdb(family_str, &tiletype).merge(&other_tiledb.db)?;
            }

            // let ip_tiledb = other.ip_bitdb(family_str, tiletype.as_str());
            // self.ip_bitdb(family_str, &tiletype).merge(&ip_tiledb.db)?;


        }

        for (device, name_to_type_map) in other.overlay_tiletypes.iter() {
            let new_map = self.overlay_tiletypes.entry(device.clone()).or_insert(BTreeMap::new());
            for (tilename, tiletypename) in name_to_type_map.iter() {
                new_map.insert(tilename.clone(), tiletypename.clone());
            }
        }
        Ok(())
    }
    pub fn tile_bitdb_from_overlays(&mut self, family: &str, tiletype: &str, overlay: &OverlayTiletype) -> Result<TileBitsData, String> {
        let tile_bits_db = TileBitsDatabase {
            pips: BTreeMap::new(),
            words: BTreeMap::new(),
            enums: BTreeMap::new(),
            conns: BTreeMap::new(),
            always_on: BTreeSet::new(),
            tile_configures_external_tiles : BTreeSet::new(),
        };
        let mut tile_bits = TileBitsData::new(tiletype, tile_bits_db);
        info!("Merge {tiletype} {:?}", overlay.overlays);

        let overlay_members : Vec<String> = overlay.overlays.clone().into_iter()
            .sorted_by(|x, y| {
                (y.starts_with("overlay"), y).cmp(&(x.starts_with("overlay"), x))
            }).collect();

        for layer in overlay_members {
            info!("Merging {layer} into {tiletype}");
            let overlay_bits = self.tile_bitdb(family, layer.as_str());
            tile_bits.merge(&overlay_bits.db)?;
        }

        Ok(tile_bits)
    }
    // Bit database for a tile by family and tile type
    pub fn tile_bitdb(&mut self, family: &str, tiletype: &str) -> &mut TileBitsData {
        let key = (family.to_string(), tiletype.to_string());
        if !self.tilebits.contains_key(&key) {
            let overlay = self.overlays().iter()
                .find(|((overlay_family, _), overlay)| {
                    family == overlay_family && overlay.contains_key(tiletype)
                })
                .map(|(_, overlay)| overlay.get(tiletype).unwrap().clone()).map(|overlay| overlay.clone());

            let tile_bits = match overlay {
                Some(overlay) => {
                    self.tile_bitdb_from_overlays(family, tiletype, &overlay).unwrap()
                }
                None => {
                    let is_overlay = tiletype.starts_with("overlays/");
                    let filename = if is_overlay {
                        format!("{}/overlays/{}.ron", family, tiletype.replace("overlays/", ""))
                    } else {
                        format!("{}/tiletypes/{}.ron", family, tiletype)
                    };
                    let tb = if self.file_exists(&filename) {
                        // read the whole file
                        let tt_ron_buf = self.read_file(&filename);
                        ron::de::from_str(&tt_ron_buf).unwrap()
                    } else {
                        debug!("No tile database found for {tiletype} at {filename} -- using empty db.");

                        TileBitsDatabase {
                            pips: BTreeMap::new(),
                            words: BTreeMap::new(),
                            enums: BTreeMap::new(),
                            conns: BTreeMap::new(),
                            always_on: BTreeSet::new(),
                            tile_configures_external_tiles : BTreeSet::new(),
                        }
                    };
                    TileBitsData::new(tiletype, tb)
                }
            };

            self.tilebits.insert(key.clone(), tile_bits);
        }

        self.tilebits.get_mut(&key).unwrap()
    }
    // Bit database for a tile by family and tile type
    pub fn ip_bitdb(&mut self, family: &str, iptype: &str) -> &mut TileBitsData {
        let key = (family.to_string(), iptype.to_string());
        if !self.ipbits.contains_key(&key) {
            // read the whole file
            let filename = format!("{}/iptypes/{}.ron", family, iptype);
            let tb = if self.file_exists(&filename) {
                let tt_ron_buf = self.read_file(&filename);
                ron::de::from_str(&tt_ron_buf).unwrap()
            } else {
                TileBitsDatabase {
                    pips: BTreeMap::new(),
                    words: BTreeMap::new(),
                    enums: BTreeMap::new(),
                    conns: BTreeMap::new(),
                    always_on: BTreeSet::new(),
                    tile_configures_external_tiles : BTreeSet::new(),
                }
            };
            self.ipbits
                .insert(key.clone(), TileBitsData::new(iptype, tb));
        }
        self.ipbits.get_mut(&key).unwrap()
    }

    pub fn reformat(&mut self) {
        debug!("Reformatting {:?}", self.tilebits.len());

        for (_, tilebits) in self.tilebits.iter_mut() {
            tilebits.dirty = true;
            tilebits.sort();
        }

        self.flush();
    }
    // Flush tile bit database changes to disk
    pub fn flush(&mut self) {
        let mut new_pips : u32 = 0;
        let mut new_enums : u32 = 0;
        let mut new_words : u32 = 0;

        for kv in self.tilebits.iter_mut() {
            let (family, tiletype) = kv.0;
            let tilebits = kv.1;
            if !tilebits.dirty {
                continue;
            }
            let pretty = PrettyConfig {
                depth_limit: 5,
                new_line: "\n".to_string(),
                indentor: "  ".to_string(),
                enumerate_arrays: false,
                separate_tuple_members: false,
            };

            tilebits.sort();
            let is_overlay = tiletype.starts_with("overlays/");

            let (dir_name, file_name) = if is_overlay {
                ("overlays", tiletype.replace("overlays", ""))
            } else {
                ("tiletypes", tiletype.clone())
            };

            debug!("Writing {}/{}/{}/{}.ron",
                self.root.as_ref().unwrap(), family, dir_name, file_name);
            new_pips += tilebits.new_pips;
            new_enums += tilebits.new_enums;
            new_words += tilebits.new_words;

            let tt_ron_buf = ron::ser::to_string_pretty(&tilebits.db, pretty).unwrap();

            fs::create_dir_all(format!("{}/{}/{}", self.root.as_ref().unwrap(), family, dir_name)).unwrap();
            File::create(format!(
                "{}/{}/{}/{}.ron",
                self.root.as_ref().unwrap(), family, dir_name, file_name
            ))
            .unwrap()
            .write_all(tt_ron_buf.as_bytes())
            .unwrap();
            tilebits.dirty = false;
        }
        for kv in self.ipbits.iter_mut() {
            let (family, iptype) = kv.0;
            let ipbits = kv.1;
            if !ipbits.dirty {
                continue;
            }
            // Check invariants for IP type configs
            assert!(ipbits.db.pips.is_empty());
            assert!(ipbits.db.conns.is_empty());

            ipbits.sort();

            let pretty = PrettyConfig {
                depth_limit: 5,
                new_line: "\n".to_string(),
                indentor: "  ".to_string(),
                enumerate_arrays: false,
                separate_tuple_members: false,
            };
            let tt_ron_buf = ron::ser::to_string_pretty(&ipbits.db, pretty).unwrap();
            File::create(format!("{}/{}/iptypes/{}.ron", self.root.as_ref().unwrap(), family, iptype))
                .unwrap()
                .write_all(tt_ron_buf.as_bytes())
                .unwrap();
            ipbits.dirty = false;
        }

        if new_pips > 0 || new_enums > 0 || new_words > 0 {
            info!("Flushing with {} new pips, {} new enum settings, {} new words", new_pips, new_enums, new_words);
        }
    }
}
