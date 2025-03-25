import os, sys, json, pymxs
import traceback

import MSVraySetup, MSLiveLinkHelpers, MSOctaneSetup, MSCoronaSetup, MSFStormSetup, MSArnoldSetup, MSRedshiftSetup

helper = MSLiveLinkHelpers.LiveLinkHelper()
VRayHelper = MSVraySetup.VraySetup()
OctaneHelper = MSOctaneSetup.OctaneSetup()
CoronaHelper = MSCoronaSetup.CoronaSetup()
FStormHelper = MSFStormSetup.FStormSetup()
ArnoldHelper = MSArnoldSetup.ArnoldSetup()
RedshiftHelper = MSRedshiftSetup.RedshiftSetup()

class LiveLinkImporter():
    Identifier = None
    isDebugMode = False

    def __init__(self):
        self._path_ = os.path.dirname(__file__).replace("\\", "/")
        self.Settings = self.loadSettings()
        self.toSelRequest = self.Settings["Material_to_Sel"]
        LiveLinkImporter.Identifier = self

    def set_Asset_Data(self, json_data):
        self.SetRenderEngine()
        if(self.Renderer == "Not-Supported"):
            msg = (
                "Your current render engine is not supported by the Bridge Plugin, "
                "so we are terminating the import process, but the Plugin is still running!"
            )
            helper.ShowMessageDialog("MS Plugin Error", msg)
            print(msg)
            return
        else:
            print("Your current render engine is " + self.Renderer)

        self.json_data = json_data
        self.parseJSON()
        self.initAssetImport()

    def parseJSON(self):
        """
        Gathers metadata from self.json_data, sets up relevant internal fields.
        """
        self.TexturesList = []
        self.Type = self.json_data["type"]
        self.mesh_transforms = []
        self.height = "1"
        self.activeLOD = self.json_data["activeLOD"]
        self.minLOD = self.json_data["minLOD"]
        self.ID = self.json_data["id"]
        self.Path = self.json_data["path"]
        self.isScatterAsset = self.CheckScatterAsset()
        self.isBillboard = self.CheckIsBillboard()

        self.isMetal = bool(self.json_data["category"] == "Metal" and self.Type == "surface")
        self.isBareMetal = bool("colorless" in [item.lower() for item in self.json_data["tags"]] and self.isMetal)
        self.isFruit = bool(
            "fruits" in [item.lower() for item in self.json_data["tags"]]
            or "fruit" in [item.lower() for item in self.json_data["tags"]]
            or "fruits" in [item.lower() for item in self.json_data["categories"]]
            or "fruit" in [item.lower() for item in self.json_data["categories"]]
        )
        self.useDisplacement = bool(
            ((self.activeLOD != "high") and self.Settings["Enable_Displacement"])
            or (self.Type != "3d")
        )
        self.isSpecularWorkflow = bool(self.json_data["workflow"] == "specular")
        self.isAlembic = helper.GetMeshType(self.json_data["meshList"])
        self.isFabric = bool(
            "fabric" in [item.lower() for item in self.json_data["tags"]]
            or "fabric" in [item.lower() for item in self.json_data["categories"]]
        )
        self.isPlant = bool(self.Type == "3dplant")
        self.isSurfaceSSS = (
            self.Type == "surface"
            and (
                "moss" in [cat.lower() for cat in self.json_data["categories"]]
                or "skin" in [cat.lower() for cat in self.json_data["categories"]]
                or "snow" in [cat.lower() for cat in self.json_data["categories"]]
            )
        )

        texturesListName = "components"
        if self.isBillboard:
            texturesListName = "components"

        self.TexturesList = []
        self.textureTypes = [obj["type"] for obj in self.json_data[texturesListName]]

        for obj in self.json_data[texturesListName]:
            texFormat = obj["format"]
            texType = obj["type"]
            texPath = obj["path"]

            # If there's a displacement map, prefer .exr if it exists
            if texType == "displacement" and self.useDisplacement:
                dirn_ = os.path.dirname(texPath)
                filen_ = os.path.splitext(os.path.basename(texPath))[0]
                possible_exr = os.path.join(dirn_, filen_ + ".exr")
                if os.path.exists(possible_exr):
                    texPath = possible_exr
                    texFormat = "exr"

            if texType == "diffuse" and "albedo" not in self.textureTypes:
                texType = "albedo"
                self.textureTypes.append("albedo")
                self.textureTypes.remove("diffuse")

            self.TexturesList.append((texFormat, texType, texPath))

        self.GeometryList = [(obj["format"], obj["path"]) for obj in self.json_data["meshList"]]

        if "name" in self.json_data.keys():
            self.Name = self.json_data["name"].replace(" ", "_")
        else:
            self.Name = os.path.basename(self.json_data["path"]).replace(" ", "_")
            if len(self.Name.split("_")) >= 2:
                self.Name = "_".join(self.Name.split("_")[:-1])

        self.materialName = self.ID + "_" + self.Name

        self.scanWidth = 1
        self.scanHeight = 1
        self.meta = None

        try:
            if "meta" in self.json_data.keys():
                self.meta = self.json_data["meta"]
                self.scanWidth = helper.GetScanWidth(self.meta)
                self.scanHeight = helper.GetScanHeight(self.meta)
                height_ = [item for item in self.meta if item["key"].lower() == "height"]
                if len(height_) >= 1:
                    self.height = str(height_[0]["value"].replace("m", ""))
                    self.height = float(self.height) * (39.37 / 2 * (self.scanWidth / 2.1))
                    if self.Type == "3d":
                        self.height = 0.005 * 39.37
        except:
            pass

    def initAssetImport(self):
        """
        Actually builds the final MaxScript string (render_setup) and executes it.
        We'll wrap it with a try/catch and log to a file.
        """
        self.Settings = self.loadSettings()
        self.toSelRequest = self.Settings["Material_to_Sel"]

        if len(self.GeometryList) > 0 and self.isAlembic and helper.GetMaxVersion() >= 2019:
            helper.SetAlembicImportSettings()

        assetData = RendererData(
            self.TexturesList,
            self.textureTypes,
            self.Type,
            self.materialName,
            self.useDisplacement,
            self.isMetal,
            self.isBareMetal,
            self.isFruit,
            self.toSelRequest,
            self.isSpecularWorkflow,
            self.scanWidth,
            self.scanHeight,
            self.meta
        )

        # Build the script
        render_setup = ""

        if not assetData.applyToSel:
            render_setup += "clearSelection()\n"

        isMultiMatAsset = helper.HasMultipleMaterial(self.meta)
        if isMultiMatAsset and "obj" in self.json_data["meshFormat"].lower():
            render_setup += helper.OpenObjImpFile()
            render_setup += helper.GetObjSetting("Objects", "SingleMesh", "isSingleMesh")
            render_setup += helper.ChangeObjSetting("Objects", "SingleMesh", "1")

        render_setup += self.MeshSetup()

        if self.toSelRequest and self.Type.lower() not in ["3dplant", "3d"]:
            render_setup = render_setup.replace("SELOPTION", "Enabled")
        else:
            render_setup = render_setup.replace("SELOPTION", "Disabled")

        if self.Renderer in ["Arnold", "Corona", "Redshift", "Octane"]:
            render_setup += self.TextureSetup()

        import MSVraySetup, MSCoronaSetup, MSFStormSetup, MSArnoldSetup, MSRedshiftSetup
        # V-Ray
        if self.Renderer == "Arnold":
            render_setup += MSArnoldSetup.ArnoldSetup().GetMaterialSetup(assetData)
        elif self.Renderer == "Corona":
            render_setup += MSCoronaSetup.CoronaSetup().GetMaterialSetup(assetData)
        elif self.Renderer == "Vray":
            render_setup += MSVraySetup.VraySetup().GetVRayRenderSetup(assetData)
        elif self.Renderer == "Redshift":
            render_setup += MSRedshiftSetup.RedshiftSetup().GetMaterialSetup(assetData)
        elif self.Renderer == "FStorm":
            import MSFStormSetup
            render_setup += MSFStormSetup.FStormSetup().GetMaterialSetup(assetData)
        elif self.Renderer == "Octane":
            import MSOctaneSetup
            render_setup += MSOctaneSetup.OctaneSetup().GetMaterialSetup(assetData)

        # Build placeholders
        maplist_ = [(item["path"], item["format"], item["type"]) for item in self.json_data["components"]]
        for map_ in maplist_:
            texture_ = map_[0]
            format_ = map_[1]
            if map_[2].lower() == "displacement":
                dirn_ = os.path.dirname(map_[0])
                filen_ = os.path.splitext(os.path.basename(map_[0]))[0]
                if os.path.exists(os.path.join(dirn_, filen_ + ".exr")):
                    texture_ = os.path.join(dirn_, filen_ + ".exr")
                    format_ = "exr"

            c_space = 1.0
            if format_.lower() in ["exr"]:
                c_space = 1.0
            if map_[2].lower() in ["albedo", "specular", "translucency"] and format_.lower() not in ["exr"]:
                c_space = 2.2

            placeholderFile = "TEX_" + map_[2].upper() + '"'
            placeholderGamma = '"CS_' + map_[2].upper() + '"'
            render_setup = render_setup.replace(placeholderFile, texture_.replace("\\", "/") + '"')
            render_setup = render_setup.replace(placeholderGamma, str(c_space))

        render_setup = render_setup.replace("MS_MATNAME", self.materialName)
        render_setup = render_setup.replace("MSTYPE", self.Type.lower())

        pathlist_ = ", ".join(
            ('"'+ item["path"].replace("\\", "/") +'"') for item in self.json_data["meshList"]
        )
        render_setup = render_setup.replace("FBXPATHLIST", pathlist_)
        render_setup = render_setup.replace("MSLOD", self.activeLOD)

        if "tags" in self.json_data.keys():
            if "fabric" in [item.lower() for item in self.json_data["tags"]]:
                render_setup = render_setup.replace("MSFABRIC", "isFabric")
            else:
                render_setup = render_setup.replace('"MSFABRIC"', "false")

            if "metal" in self.json_data["tags"] or "metal" in self.json_data["categories"]:
                render_setup = render_setup.replace("MSMETAL", "isMetal")

            if (
                "colorless" in self.json_data["tags"]
                and "metal" in self.json_data["tags"]
            ) or ("metal" in self.json_data["categories"]):
                render_setup = render_setup.replace("MSBAREMETAL", "isBareMetal")

            if "fruits" in self.json_data["tags"]:
                render_setup = render_setup.replace("MSFRUIT", "isFruit")

            if "isCustom" in self.json_data.keys():
                if self.json_data["isCustom"] == True:
                    render_setup = render_setup.replace("MSCUSTOM", "isCustom")

        render_setup = render_setup.replace("MS_METAL", str(self.isMetal).lower())
        render_setup = render_setup.replace("MS_BAREMETAL", str(self.isBareMetal).lower())
        render_setup = render_setup.replace("MS_FABRIC", str(self.isFabric).lower())
        render_setup = render_setup.replace("MS_FRUIT", str(self.isFruit).lower())
        render_setup = render_setup.replace("MS_DISP", str(self.useDisplacement).lower())
        render_setup = render_setup.replace("MS_PLANT", str(self.isPlant).lower())
        render_setup = render_setup.replace("MS_SSS", str(self.isSurfaceSSS).lower())

        # If Corona or Redshift placeholders exist
        if self.Renderer.lower() == "corona":
            render_setup = render_setup.replace(
                "SPECULARTOIOR",
                os.path.join(self._path_, "SpecularToIOR.CUBE").replace("\\", "/")
            )
            render_setup = render_setup.replace("MS_HEIGHT", str(self.height))

        if self.Renderer.lower() == "redshift":
            render_setup = render_setup.replace("MS_HEIGHT", str(self.height))

        if self.isScatterAsset:
            render_setup += self.ScatterSetup()
            render_setup = render_setup.replace("SCATTERPARENTNAME", self.materialName)

        if isMultiMatAsset and "obj" in self.json_data["meshFormat"].lower():
            render_setup += helper.ResetObjIniValue("Objects", "SingleMesh", "isSingleMesh")

        if self.Renderer == "Octane":
            updated_line = ""
            for script_line in render_setup.splitlines():
                if "TEX_" in script_line:
                    updated_line = "--" + script_line
                    render_setup = render_setup.replace(script_line, updated_line)

        # 1) We'll wrap that in a MaxScript try/catch
        # 2) We'll write the entire final script to disk
        msLogFile = "C:/temp/megascans_script.ms"
        msTryCatch = f"""
try(
{render_setup}
)
catch(errMsg) (
    local logFileHandle = createfile "C:/temp/megascans_error.log"
    format "MAXScript Error: %\\n" (getCurrentException()) to:logFileHandle
    format "------------------\\n" to:logFileHandle
    close logFileHandle
)
"""

        # Write this final script to disk so we can see EXACTLY what's run
        try:
            with open(msLogFile, "w") as f:
                f.write(msTryCatch)
        except Exception as e:
            print("Error writing to msLogFile:", e)

        # Finally, run msTryCatch
        try:
            if not LiveLinkImporter.isDebugMode:
                pymxs.runtime.execute(msTryCatch)
        except Exception as e:
            # If it bombs at the python level, log it
            pythonLogFile = "C:/temp/megascans_python_error.log"
            with open(pythonLogFile, "a") as f:
                f.write("=== Python-level Exception ===\n")
                f.write(str(e) + "\n")
                f.write(traceback.format_exc() + "\n")
            print(f"Python-level exception. See {pythonLogFile} for details.")

    def SetRenderEngine(self):
        selectedRenderer = str(pymxs.runtime.execute("renderers.current"))
        selectedRenderer = selectedRenderer.lower()
        self.Renderer = "Not-Supported"
        if "corona" in selectedRenderer:
            self.Renderer = "Corona"
        elif "redshift" in selectedRenderer:
            self.Renderer = "Redshift"
        elif "v_ray" in selectedRenderer:
            self.Renderer = "Vray"
        elif "octane" in selectedRenderer:
            self.Renderer = "Octane"
        elif "fstorm" in selectedRenderer:
            self.Renderer = "FStorm"
        elif "arnold" in selectedRenderer:
            self.Renderer = "Arnold"

    def MeshSetup(self):
        return ("""
        FBXImporterSetParam "ScaleFactor" 1
        selToMat = "SELOPTION"
        old_sel = for s in selection collect s

        assetType = "MSTYPE"
        assetLOD = "MSLOD"
        isFabric = "MSFABRIC"
        isMetal = "MSMETAL"
        isBareMetal = "MSBAREMETAL"
        isCustom = "MSCUSTOM"
        isFruit = "MSFRUIT"

        
        MSFabric = MS_FABRIC
        MSMetal = MS_METAL
        MSBareMetal = MS_BAREMETAL
        MSFruit = MS_FRUIT
        Disp = MS_DISP
        MSPlant = MS_PLANT
        SSSSurface = MS_SSS

        meshes_ = #(FBXPATHLIST)

        oldObj = objects as array

        for geo in meshes_ do (
            ImportFile geo #noprompt
        )

        newObj = for o in objects where findItem oldObj o == 0 collect o

        select newObj
        if (selToMat == "Enabled") do (
            selectMore old_sel
        )

        CurOBJs = for s in selection collect s
        """)

    def TextureSetup(self):
        if self.Renderer == "Octane":
            return ("""
            --Bitmaptextures

            albedoBitmap = undefined
            diffuseBitmap = undefined
            roughnessBitmap = undefined
            opacityBitmap = undefined
            normalBitmap = undefined
            metallicBitmap = undefined
            translucencyBitmap = undefined
            transmissionBitmap = undefined
            displacementBitmap = undefined
            specularBitmap = undefined
            glossBitmap = undefined
            FuzzBitmap = undefined
            aoBitmap = undefined
            cavityBitmap = undefined
            bumpBitmap = undefined
            normalbumpBitmap = undefined

            albedoBitmap = Bitmaptexture fileName: "TEX_ALBEDO" gamma: "CS_ALBEDO"
            diffuseBitmap = Bitmaptexture fileName: "TEX_ALBEDO" gamma: "CS_ALBEDO"
            roughnessBitmap = Bitmaptexture fileName: "TEX_ROUGHNESS" gamma: "CS_ROUGHNESS"
            opacityBitmap = Bitmaptexture fileName: "TEX_OPACITY" gamma: "CS_OPACITY"
            normalBitmap = Bitmaptexture fileName: "TEX_NORMAL" gamma: "CS_NORMAL"
            metallicBitmap = Bitmaptexture fileName: "TEX_METALNESS" gamma: "CS_METALNESS"
            translucencyBitmap = Bitmaptexture fileName: "TEX_TRANSLUCENCY" gamma: "CS_TRANSLUCENCY"
            transmissionBitmap = Bitmaptexture fileName: "TEX_TRANSMISSION" gamma: "CS_TRANSMISSION"
            displacementBitmap = Bitmaptexture fileName: "TEX_DISPLACEMENT" gamma: "CS_DISPLACEMENT"
            specularBitmap = Bitmaptexture fileName: "TEX_SPECULAR" gamma: "CS_SPECULAR"
            glossBitmap = Bitmaptexture fileName: "TEX_GLOSS" gamma: "CS_GLOSS"
            FuzzBitmap = Bitmaptexture fileName: "TEX_FUZZ" gamma: "CS_FUZZ"
            aoBitmap = Bitmaptexture fileName: "TEX_AO" gamma: "CS_AO"
            cavityBitmap = Bitmaptexture fileName: "TEX_CAVITY" gamma: "CS_CAVITY"
            bumpBitmap = Bitmaptexture fileName: "TEX_BUMP" gamma: "CS_BUMP"
            normalbumpBitmap = Bitmaptexture fileName: "TEX_NORMALBUMP" gamma: "CS_NORMALBUMP"
            """)
        else:
            return ("""
            --Bitmaps

            albedoBitmap = openBitmap "TEX_ALBEDO" gamma: "CS_ALBEDO"
            diffuseBitmap = openBitmap "TEX_ALBEDO" gamma: "CS_ALBEDO"
            roughnessBitmap = openBitmap "TEX_ROUGHNESS" gamma: "CS_ROUGHNESS"
            opacityBitmap = openBitmap "TEX_OPACITY" gamma: "CS_OPACITY"
            normalBitmap = openBitmap "TEX_NORMAL" gamma: "CS_NORMAL"
            metallicBitmap = openBitmap "TEX_METALNESS" gamma: "CS_METALNESS"
            translucencyBitmap = openBitmap "TEX_TRANSLUCENCY" gamma: "CS_TRANSLUCENCY"
            transmissionBitmap = openBitmap "TEX_TRANSMISSION" gamma: "CS_TRANSMISSION"
            displacementBitmap = openBitmap "TEX_DISPLACEMENT" gamma: "CS_DISPLACEMENT"
            specularBitmap = openBitmap "TEX_SPECULAR" gamma: "CS_SPECULAR"
            glossBitmap = openBitmap "TEX_GLOSS" gamma: "CS_GLOSS"
            FuzzBitmap = openBitmap "TEX_FUZZ" gamma: "CS_FUZZ"
            aoBitmap = openBitmap "TEX_AO" gamma: "CS_AO"
            cavityBitmap = openBitmap "TEX_CAVITY" gamma: "CS_CAVITY"
            bumpBitmap = openBitmap "TEX_BUMP" gamma: "CS_BUMP"
            normalbumpBitmap = openBitmap "TEX_NORMALBUMP" gamma: "CS_NORMALBUMP"
            """)

    def ScatterSetup(self):
        return ("""
        actionMan.executeAction 0 "40043"  -- Selection: Select None

        parentObject = Point pos:[0,0,0] name:"SCATTERPARENTNAME"

        select CurOBJs
        for o in selection do o.parent = parentObject
        actionMan.executeAction 0 "40043"  -- Selection: Select None
        """)

    def CheckScatterAsset(self):
        if self.Type == "3d":
            if (
                "scatter" in self.json_data["categories"]
                or "scatter" in self.json_data["tags"]
                or "cmb_asset" in self.json_data["categories"]
                or "cmb_asset" in self.json_data["tags"]
            ):
                return True
        return False

    def CheckIsBillboard(self):
        if self.Type == "3dplant":
            if self.activeLOD == self.minLOD:
                return True
        return False

    def loadSettings(self):
        if os.path.exists(os.path.join(self._path_, "Settings.json")):
            with open(os.path.join(self._path_, "Settings.json"), 'r') as fl_:
                self.Settings = json.load(fl_)
        else:
            self.createSettings()
        return self.Settings

    def createSettings(self):
        self.Settings = self.defaultSettings()
        output_ = json.dumps(self.Settings, sort_keys=True, ensure_ascii=False, indent=2)
        with open(os.path.join(self._path_, "Settings.json"), 'w') as outfile:
            json.dump(self.Settings, outfile)

    def defaultSettings(self):
        self.Settings = ({
            "Material_to_Sel": True,
            "WinGeometry": [0, 0, 0, 0],
            "Enable_Displacement": True
        })
        return self.Settings

    def updateSettings(self, settings):
        if os.path.exists(os.path.join(self._path_, "Settings.json")):
            with open(os.path.join(self._path_, "Settings.json"), 'w') as outfile:
                json.dump(settings, outfile)
        else:
            self.Settings = settings
            output_ = json.dumps(self.Settings, sort_keys=True, ensure_ascii=False, indent=2)
            with open(os.path.join(self._path_, "Settings.json"), 'w') as outfile:
                json.dump(self.Settings, outfile)

    def getPref(self, request):
        return self.Settings[request]


class RendererData():
    def __init__(
        self,
        textureList,
        textureTypes,
        assetType,
        materialName,
        useDisplacement,
        isMetal,
        isBareMetal,
        isFruit,
        applyToSel,
        isSpecular,
        width,
        height,
        meta
    ):
        self.textureList = textureList
        self.textureTypes = textureTypes
        self.assetType = assetType
        self.materialName = materialName
        self.useDisplacement = useDisplacement
        self.isMetal = isMetal
        self.isBareMetal = isBareMetal
        self.isFruit = isFruit
        self.applyToSel = applyToSel
        self.isSpecular = isSpecular
        self.width = width
        self.height = height
        self.meta = meta
