

class PinSetting:
    def __init__(self, name, dir, desc=""):
        self.name = name
        self.dir = dir
        self.desc = desc

class WordSetting:
    def __init__(self, name, bits, desc=""):
        self.name = name
        self.bits = bits
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
    (* \\dm:primitive ="{self.name}", \\dm:programming ="MODE:OSC_CORE ${config}", \\dm:site ="{site}" *) 
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
    [
        EnumSetting("MODE", ["NONE", "OSC_CORE"],
                desc="OSC_CORE primitive mode"),
        WordSetting("HF_CLK_DIV", 8,
                    desc="high frequency oscillator output divider"),
        WordSetting("HF_SED_SEC_DIV", 8,
                    desc="high frequency oscillator output divider"),
        EnumSetting("DTR_EN", ["ENABLED", "DISABLED"]),
        EnumSetting("HF_FABRIC_EN", ["ENABLED", "DISABLED"],
                    desc="enable HF oscillator trimming from input pins"),
        EnumSetting("HF_OSC_EN", ["ENABLED", "DISABLED"],
                    desc="enable HF oscillator"),
        EnumSetting("HFDIV_FABRIC_EN", ["ENABLED", "DISABLED"],
                    desc="enable HF divider from parameter"),
        EnumSetting("LF_FABRIC_EN", ["ENABLED", "DISABLED"],
                    desc="enable LF oscillator trimming from input pins"),
        EnumSetting("LF_OUTPUT_EN", ["ENABLED", "DISABLED"],
                    desc="enable LF oscillator output"),
        EnumSetting("DEBUG_N", ["ENABLED", "DISABLED"],
                    desc="enable debug mode"),
    ],
    [
        PinSetting("HFCLKOUT", "out"),
        PinSetting("HFSDSCEN", "in")
    ]
)

oscd_core = PrimitiveDefinition(
    name="OSCD_CORE",
    settings = [
        EnumSetting("MODE", ["NONE", "OSCD_CORE"], desc="OSC_CORED primitive mode"),
        EnumSetting("DTR_EN", ["ENABLED", "DISABLED"],
                    desc="DTR block enable from MIB"),

        WordSetting("HF_CLK_DIV", 8,
                    desc="HF oscillator user output divider (div2–div256)"),

        WordSetting("HF_SED_SEC_DIV", 8,
                    desc="HF oscillator SED/secondary divider (div2–div256)"),

        EnumSetting("HF_FABRIC_EN", ["ENABLED", "DISABLED"],
                    desc="HF oscillator trim source mux select"),

        EnumSetting("HF_OSC_EN", ["ENABLED", "DISABLED"],
                    desc="HF oscillator enable"),

        EnumSetting("LF_FABRIC_EN", ["ENABLED", "DISABLED"],
                    desc="LF oscillator trim source mux select"),

        EnumSetting("LF_OUTPUT_EN", ["ENABLED", "DISABLED"],
                    desc="LF clock output enable"),

        EnumSetting("DEBUG_N", ["ENABLED", "DISABLED"],
                    desc="Ignore SLEEP/STOP during USER mode when disabled"),
    ],
    pins=[
        PinSetting("HFOUTEN", dir="in",
                  desc="HF clock (225MHz) output enable (test only)"),
        PinSetting("HFSDSCEN", dir="in",
                  desc="HF user clock output enable"),
        PinSetting("HFOUTCIBEN", dir="in",
                  desc="CIB control to enable/disable HF oscillator during user mode"),
        PinSetting("REBOOT", dir="in",
                  desc="CIB control to enable/disable hf_clk_config output"),
        PinSetting("HFCLKOUT", dir="out",
                   desc="450MHz with programmable divider (2–256) to user"),
        PinSetting("LFCLKOUT", dir="out",
                   desc="Low frequency clock output after div4 (32kHz)"),
        PinSetting("HFCLKCFG", dir="out",
                   desc="450MHz clock to configuration block"),
        PinSetting("HFSDCOUT", dir="out",
                   desc="450MHz with programmable divider (2–256) to configuration"),
    ],

)