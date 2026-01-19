

class PinSetting:
    def __init__(self, name, dir):
        self.name = name

class WordSetting:
    def __init__(self, name, states, desc=""):
        self.name = name
        self.states = states
        self.desc = desc

class EnumSetting:
    def __init__(self, name, values, mux = False, desc=""):
        self.name = name
        self.values = values
        self.desc = desc
        self.mux = mux
        
class PrimitiveDefinition:
    def __init__(self, name, settings, pins = []):
        self.name = name
        self.settings = settings
        self.pins = pins

    def build(self, ctx, site, programming, **kwargs):
        return f"""
    (* \dm:primitive ="{self.name}", \dm:programming ="MODE:OSC_CORE ${config}", \dm:site ="{site}" *) 
    {self.name} {self.name}_{idx} ( );
        """
        
lram_core = PrimitiveDefinition(
    "LRAM_CORE",
        [
            EnumSetting("MODE", ["NONE", "LRAM_CORE"], desc="LRAM primitive mode"),
            EnumSetting("ASYNC_RST_RELEASE", ["SYNC", "ASYNC"],
                desc="LRAM reset release configuration"),
            EnumSetting("DATA_PRESERVE", ["DISABLE", "ENABLE"],
                desc="LRAM data preservation across resets"),
            EnumSetting("EBR_SP_EN", ["DISABLE", "ENABLE"],
                desc="EBR single port mode"),
            EnumSetting("ECC_BYTE_SEL", ["ECC_EN", "BYTE_EN"]),
            EnumSetting("GSR", ["ENABLED", "DISABLED"],
                desc="LRAM global set/reset mask"),
            EnumSetting("OUT_REGMODE_A", ["NO_REG", "OUT_REG"],
                desc="LRAM output pipeline register A enable"),
            EnumSetting("OUT_REGMODE_B", ["NO_REG", "OUT_REG"],
                desc="LRAM output pipeline register B enable"),
            EnumSetting("RESETMODE", ["SYNC", "ASYNC"],
                desc="LRAM sync/async reset select"),
            EnumSetting("RST_AB_EN", ["RESET_AB_DISABLE", "RESET_AB_ENABLE"],
                desc="LRAM reset A/B enable"),
            EnumSetting("SP_EN", ["DISABLE", "ENABLE"],
                desc="LRAM single port mode"),
            EnumSetting("UNALIGNED_READ", ["DISABLE", "ENABLE"],
                desc="LRAM unaligned read support"),
            EnumSetting("CLKMUX",  ["#SIG", "#INV"], desc="LRAM CLK inversion control"),
            EnumSetting("CSAMUX",  ["#SIG", "#INV"], desc="LRAM CSA inversion control"),
            EnumSetting("CSBMUX",  ["#SIG", "#INV"], desc="LRAM CSB inversion control"),
            EnumSetting("RSTAMUX", ["#SIG", "#INV"], desc="LRAM RSTA inversion control"),
            EnumSetting("RSTBMUX", ["#SIG", "#INV"], desc="LRAM RSTB inversion control"),
            EnumSetting("WEAMUX",  ["#SIG", "#INV"], desc="LRAM WEA inversion control"),
            EnumSetting("WEBMUX",  ["#SIG", "#INV"], desc="LRAM WEB inversion control"),
    ]
)

iologic_core = PrimitiveDefinition(
    "IOLOGIC_CORE",
    [
        WordSetting("DELAY.DEL_VALUE", 7),
        EnumSetting("DELAY.COARSE_DELAY", ["0NS", "0P8NS", "1P6NS"]),
        EnumSetting("DELAY.COARSE_DELAY_MODE", ["DYNAMIC", "STATIC"]),
        EnumSetting("DELAY.EDGE_MONITOR", ["ENABLED", "DISABLED"]),
        EnumSetting("DELAY.WAIT_FOR_EDGE", ["ENABLED", "DISABLED"]),        
    ]
)

siologic_core = PrimitiveDefinition(
    "SIOLOGIC_CORE",
    iologic_core.settings +
    [
        EnumSetting(f":{n}", ["#SIG", "#OFF"])
        for n in 
        ["CIBCRS0", "CIBCRS1", "RANKSELECT", "RANKENABLE", "RANK0UPDATE", "RANK1UPDATE"]
    ]
)

osc_core = PrimitiveDefinition(
    "OSC_CORE",
    [],
    [
        PinSetting("HFCLKOUT", "out"),
        PinSetting("HFSDSCEN", "in")
    ]
)
