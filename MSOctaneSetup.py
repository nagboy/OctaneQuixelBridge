import os, sys, json
import MSLiveLinkHelpers

helper = MSLiveLinkHelpers.LiveLinkHelper()

class OctaneSetup():
    def GetMaterialSetup(self, assetData):
        """
        Creates either a single or multi-material for Octane without using any Slate Editor functionality.
        """
        # Debug: Write assetData to C:\temp\assetData.json
        #debug_path = r"C:\temp\assetData.json"
        #os.makedirs(os.path.dirname(debug_path), exist_ok=True)
        #try:
        #    with open(debug_path, 'w') as f:
        #        json.dump(vars(assetData), f, indent=4, default=str)
        #except Exception as e:
        #    print(f"Failed to write assetData to {debug_path}: {e}")

        # Extract displacement amount from meta
        displacement_amount = 0.013  # Default
        for entry in assetData.meta:
            if entry["key"] == "height":
                try:
                    displacement_amount = float(entry["value"].split()[0])  # e.g., "0.009 m" -> 0.009
                except (ValueError, IndexError):
                    pass

        # Extract scanArea scale from meta
        scan_scale1 = 1.0
        scan_scale2 = 1.0
        for entry in assetData.meta:
            if entry["key"].lower() == "scanarea":
                val = entry["value"]  # e.g. "0.6x0.6 m" or "60x60 cm"
                parts = val.split()
                if len(parts) >= 1:
                    dims = parts[0]  # "0.6x0.6" or "60x60"
                    dims_parts = dims.split("x")
                    if len(dims_parts) == 2:
                        try:
                            scale1 = float(dims_parts[0])
                            scale2 = float(dims_parts[1])
                        except:
                            scale1 = 1.0
                            scale2 = 1.0
                    else:
                        scale1 = 1.0
                        scale2 = 1.0
                else:
                    scale1 = 1.0
                    scale2 = 1.0
                unit = "m"
                if len(parts) >= 2:
                    unit = parts[1].lower()
                if unit.startswith("cm"):
                    scale1 /= 100.0
                    scale2 /= 100.0
                scan_scale1 = scale1
                scan_scale2 = scale2
                break

        # Extract LoD from displacement filename
        displacement_lod = 13  # Default to 8k
        for tex_type, tex_name, tex_path in assetData.textureList:
            if tex_name == "displacement":
                filename = tex_path.lower()
                if "1k" in filename:
                    displacement_lod = 10  # 1024x1024
                elif "2k" in filename:
                    displacement_lod = 11  # 2048x2048
                elif "4k" in filename:
                    displacement_lod = 12  # 4096x4096
                elif "8k" in filename:
                    displacement_lod = 13  # 8192x8192
                break

        # Check for "polished" in textureList
        has_polished = False
        for tex_entry in assetData.textureList:
            if "polished" in str(tex_entry).lower():
                has_polished = True
                break

        materialScript = ""

        # If multiple sub-materials exist, build a Multi/Sub material
        if helper.HasMultipleMaterial(assetData.meta):
            multiNodeName = "MutliMaterial"
            materialScript += f"""
            {multiNodeName} = MultiSubMaterial()
            {multiNodeName}.name = "{assetData.materialName}"
            {multiNodeName}.materialList.count = {helper.GetNumberOfUniqueMaterial(assetData.meta)}
            """
            index = 1
            matsData = helper.ExtractMatData(assetData.meta)
            for matData in matsData:
                nodeName = f"MatNode_{index}"
                matName = f"{assetData.materialName}_{index}"
                if matData.matType == "glass":
                    materialScript += self.GetGlassMaterial(nodeName, matName)
                else:
                    materialScript += self.GetOpaqueMaterial(nodeName, matName,
                                                             assetData.useDisplacement,
                                                             assetData.assetType,
                                                             displacement_amount,
                                                             displacement_lod,
                                                             has_polished,
                                                             scan_scale1,
                                                             scan_scale2)
                zeroBased = index - 1
                materialScript += f"""
                {multiNodeName}.materialList[{zeroBased+1}] = {nodeName}
                """
                index += 1

            materialScript += f"""
            for o in selection do o.material = {multiNodeName}
            {multiNodeName}.showInViewport = true
            """
        else:
            # Single material route
            nodeName = "MatNode"
            materialScript += self.GetOpaqueMaterial(nodeName, assetData.materialName,
                                                     assetData.useDisplacement,
                                                     assetData.assetType,
                                                     displacement_amount,
                                                     displacement_lod,
                                                     has_polished,
                                                     scan_scale1,
                                                     scan_scale2)
            materialScript += f"""
            for o in selection do o.material = {nodeName}
            {nodeName}.showInViewport = true
            """
        materialScript += helper.RearrangeMaterialGraph()
        helper.DeselectEverything()
        return materialScript

    def GetOpaqueMaterial(self, nodeName, matName, useDisplacement, assetType, displacement_amount, displacement_lod, has_polished, scan_scale1, scan_scale2):
        """
        Creates an Octane universal_material for opaque surfaces.
        Before each texture assignment, the slot’s input type is set to 2.
        All RGB_image and Grayscale_image nodes share the albedo’s _2D_transformation and Mesh_UV_projection.
        """
        # Create displacement snippet with LoD and amount from computed values
        displacementSnippet = "--No displacement"
        if useDisplacement and assetType.lower() not in ["3dplant"]:
            displacementSnippet = f"""
            if displacementBitmap != undefined then (
                if doesFileExist displacementBitmap.filename do (
                    {nodeName}.displacement = Texture_displacement()
                    {nodeName}.displacement.texture_input_type = 2
                    {nodeName}.displacement.amount = {displacement_amount}
                    {nodeName}.displacement.levelOfDetail = {displacement_lod}
                    {nodeName}.displacement.black_level = 0.5

                    {nodeName}.displacement.texture_tex = Grayscale_image()
                    {nodeName}.displacement.texture_tex.gamma = 1.0
                    {nodeName}.displacement.texture_tex.colorSpace = "_OctaneBuildIn_LINEAR_sRGB"
                    {nodeName}.displacement.texture_tex.filename = displacementBitmap.filename
                    {nodeName}.displacement.texture_tex.transform = trans2D
                    {nodeName}.displacement.texture_tex.Projection = meshUV
                )
            )
            """

        # Coating snippet for polished surfaces
        coatingSnippet = ""
        if has_polished:
            coatingSnippet = f"""
            {nodeName}.coating_input_type = 0  -- Value mode
            {nodeName}.coating_value = 1.0     -- Enable coating
            {nodeName}.coatingRoughness_input_type = 0  -- Value mode
            {nodeName}.coatingRoughness_value = 0.01    -- Smooth coating
            """

        matScript = f"""
        {nodeName} = universal_material()
        {nodeName}.name = "{matName}"
        -- Set all texture input types to "texture" mode (2)
        {nodeName}.albedo_input_type = 2
        {nodeName}.metallic_input_type = 2
        {nodeName}.roughness_input_type = 2
        {nodeName}.opacity_input_type = 2
        {nodeName}.specular_input_type = 2
        {nodeName}.normal_input_type = 2
        {nodeName}.transmission_input_type = 2

        -- Create shared transform and projection nodes for albedo
        trans2D = _2D_transformation()
        trans2D.name = "Shared_Transform_9876"
        trans2D.scale1 = {scan_scale1}
        trans2D.scale2 = {scan_scale2}
        meshUV = Mesh_UV_projection()
        meshUV.name = "Shared_Projection_5678"

        -- Albedo (set up base texture with shared transform/projection)
        if albedoBitmap != undefined then (
            if doesFileExist albedoBitmap.filename do (
                {nodeName}.albedo_tex = RGB_image()
                {nodeName}.albedo_tex.gamma = 2.2
                {nodeName}.albedo_tex.colorSpace = "_OctaneBuildIn_sRGB"
                {nodeName}.albedo_tex.filename = albedoBitmap.filename
                {nodeName}.albedo_tex.transform = undefined
                {nodeName}.albedo_tex.Projection = undefined
                {nodeName}.albedo_tex.transform = trans2D
                {nodeName}.albedo_tex.Projection = meshUV
            )
        )

        -- Metallic
        if metallicBitmap != undefined then (
            if doesFileExist metallicBitmap.filename do (
                {nodeName}.metallic_tex = Grayscale_image()
                {nodeName}.metallic_tex.gamma = 1.0
                {nodeName}.metallic_tex.colorSpace = "_OctaneBuildIn_LINEAR_sRGB"
                {nodeName}.metallic_tex.filename = metallicBitmap.filename
                {nodeName}.metallic_tex.transform = undefined
                {nodeName}.metallic_tex.Projection = undefined
                {nodeName}.metallic_tex.transform = trans2D
                {nodeName}.metallic_tex.Projection = meshUV
            )
        )

        -- Roughness
        if roughnessBitmap != undefined then (
            if doesFileExist roughnessBitmap.filename then (
                {nodeName}.roughness_tex = Grayscale_image()
                {nodeName}.roughness_tex.gamma = 1.0
                {nodeName}.roughness_tex.colorSpace = "_OctaneBuildIn_LINEAR_sRGB"
                {nodeName}.roughness_tex.filename = roughnessBitmap.filename
                {nodeName}.roughness_tex.transform = undefined
                {nodeName}.roughness_tex.Projection = undefined
                {nodeName}.roughness_tex.transform = trans2D
                {nodeName}.roughness_tex.Projection = meshUV
            )
        )
        else if glossBitmap != undefined then (
            if doesFileExist glossBitmap.filename then (
                {nodeName}.roughness_tex = Grayscale_image()
                {nodeName}.roughness_tex.gamma = 1.0
                {nodeName}.roughness_tex.colorSpace = "_OctaneBuildIn_LINEAR_sRGB"
                {nodeName}.roughness_tex.filename = glossBitmap.filename
                {nodeName}.roughness_tex.transform = undefined
                {nodeName}.roughness_tex.Projection = undefined
                {nodeName}.roughness_tex.transform = trans2D
                {nodeName}.roughness_tex.Projection = meshUV
            )
        )

        -- Specular
        if specularBitmap != undefined then (
            if doesFileExist specularBitmap.filename then (
                {nodeName}.specular_tex = RGB_image()
                {nodeName}.specular_tex.gamma = 1.0
                {nodeName}.specular_tex.colorSpace = "_OctaneBuildIn_LINEAR_sRGB"
                {nodeName}.specular_tex.filename = specularBitmap.filename
                {nodeName}.specular_tex.transform = undefined
                {nodeName}.specular_tex.Projection = undefined
                {nodeName}.specular_tex.transform = trans2D
                {nodeName}.specular_tex.Projection = meshUV
            )
        )

        -- Normal
        if normalBitmap != undefined then (
            if doesFileExist normalBitmap.filename do (
                {nodeName}.normal_tex = RGB_image()
                {nodeName}.normal_tex.gamma = 1.0
                {nodeName}.normal_tex.colorSpace = "_OctaneBuildIn_LINEAR_sRGB"
                {nodeName}.normal_tex.filename = normalBitmap.filename
                {nodeName}.normal_tex.transform = undefined
                {nodeName}.normal_tex.Projection = undefined
                {nodeName}.normal_tex.transform = trans2D
                {nodeName}.normal_tex.Projection = meshUV
            )
        )

        -- Displacement (already updated in snippet above)
        {displacementSnippet}

        -- Coating for polished surfaces
        {coatingSnippet}

        -- Opacity
        if opacityBitmap != undefined then (
            if doesFileExist opacityBitmap.filename do (
                {nodeName}.opacity_tex = Grayscale_image()
                {nodeName}.opacity_tex.gamma = 1.0
                {nodeName}.opacity_tex.colorSpace = "_OctaneBuildIn_LINEAR_sRGB"
                {nodeName}.opacity_tex.filename = opacityBitmap.filename
                {nodeName}.opacity_tex.transform = undefined
                {nodeName}.opacity_tex.Projection = undefined
                {nodeName}.opacity_tex.transform = trans2D
                {nodeName}.opacity_tex.Projection = meshUV
            )
        )

        -- Transmission / Translucency
        if translucencyBitmap != undefined then (
            if doesFileExist translucencyBitmap.filename then (
                {nodeName}.transmission_tex = RGB_image()
                {nodeName}.transmission_tex.gamma = 2.2
                {nodeName}.transmission_tex.colorSpace = "_OctaneBuildIn_sRGB"
                {nodeName}.transmission_tex.filename = translucencyBitmap.filename
                {nodeName}.transmission_tex.transform = undefined
                {nodeName}.transmission_tex.Projection = undefined
                {nodeName}.transmission_tex.transform = trans2D
                {nodeName}.transmission_tex.Projection = meshUV
            )
        )
        else if transmissionBitmap != undefined then (
            if doesFileExist transmissionBitmap.filename then (
                {nodeName}.transmission_tex = Grayscale_image()
                {nodeName}.transmission_tex.gamma = 1.0
                {nodeName}.transmission_tex.colorSpace = "_OctaneBuildIn_LINEAR_sRGB"
                {nodeName}.transmission_tex.filename = transmissionBitmap.filename
                {nodeName}.transmission_tex.transform = undefined
                {nodeName}.transmission_tex.Projection = undefined
                {nodeName}.transmission_tex.transform = trans2D
                {nodeName}.transmission_tex.Projection = meshUV
            )
        )

        -- Bump, Cavity, Fuzz (these nodes are created but not connected)
        if bumpBitmap != undefined then (
            if doesFileExist bumpBitmap.filename then (
                local BumpNode = Grayscale_image()
                BumpNode.gamma = 1.0
                BumpNode.colorSpace = "_OctaneBuildIn_LINEAR_sRGB"
                BumpNode.filename = bumpBitmap.filename
                BumpNode.transform = undefined
                BumpNode.Projection = undefined
                BumpNode.transform = trans2D
                BumpNode.Projection = meshUV
            )
        )
        if cavityBitmap != undefined then (
            if doesFileExist cavityBitmap.filename then (
                local CavityNode = Grayscale_image()
                CavityNode.gamma = 1.0
                CavityNode.colorSpace = "_OctaneBuildIn_LINEAR_sRGB"
                CavityNode.filename = cavityBitmap.filename
                CavityNode.transform = undefined
                CavityNode.Projection = undefined
                CavityNode.transform = trans2D
                CavityNode.Projection = meshUV
            )
        )
        if fuzzBitmap != undefined then (
            if doesFileExist fuzzBitmap.filename then (
                local FuzzNode = Grayscale_image()
                FuzzNode.gamma = 1.0
                FuzzNode.colorSpace = "_OctaneBuildIn_LINEAR_sRGB"
                FuzzNode.filename = fuzzBitmap.filename
                FuzzNode.transform = undefined
                FuzzNode.Projection = undefined
                FuzzNode.transform = trans2D
                FuzzNode.Projection = meshUV
            )
        )
        """
        return matScript

    def GetGlassMaterial(self, nodeName, matName):
        """
        Creates a specular_material for glass. Only the roughness and normal channels are set.
        """
        matScript = f"""
        {nodeName} = specular_material()
        {nodeName}.name = "{matName}"
        -- Set texture input types for the channels used
        {nodeName}.roughness_input_type = 2
        {nodeName}.normal_input_type = 2

        -- Roughness
        if roughnessBitmap != undefined then (
            if doesFileExist roughnessBitmap.filename then (
                {nodeName}.roughness_tex = Grayscale_image()
                {nodeName}.roughness_tex.gamma = 1.0
                {nodeName}.roughness_tex.colorSpace = "_OctaneBuildIn_LINEAR_sRGB"
                {nodeName}.roughness_tex.filename = roughnessBitmap.filename
            )
        )
        else if glossBitmap != undefined then (
            if doesFileExist glossBitmap.filename then (
                {nodeName}.roughness_tex = Grayscale_image()
                {nodeName}.roughness_tex.gamma = 1.0
                {nodeName}.roughness_tex.colorSpace = "_OctaneBuildIn_LINEAR_sRGB"
                {nodeName}.roughness_tex.filename = glossBitmap.filename
            )
        )

        -- Normal
        if normalBitmap != undefined then (
            if doesFileExist normalBitmap.filename do (
                {nodeName}.normal_tex = RGB_image()
                {nodeName}.normal_tex.gamma = 1.0
                {nodeName}.normal_tex.colorSpace = "_OctaneBuildIn_LINEAR_sRGB"
                {nodeName}.normal_tex.filename = normalBitmap.filename
            )
        )

        {nodeName}.index = 1.5
        """
        return matScript

    def _IsGlassAsset(self, meta):
        return False

    def createTransformNode(self, assetType):
        return """
        useTransformNode = False
        """
