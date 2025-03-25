# **Quixel Plugin Patch for 3ds Max with OctaneRender Support**

**Tested on:**  
- 3ds Max 2024 and 2025

**Features:**  
- **Handles all texture types**  
- **Sets correct colorspace:**  
- **Sets correct gamma:**  
- **Sets correct scale:**  
- **Creates one shared UV/2D transform node** for all maps  
- **Handles displacement correctly:**  
  - Sets correct LoD based on map size  
  - Sets correct height

**Installation Instructions:**  
1. **Download and install the official Quixel plugin** (version 5.5) from [Quixel Plugins](https://quixel.com/plugins/).  
2. **Edit the Quixel.ms script:**  
   - Place this line in `Quixel.ms` (located at:  
     `C:\Users\username\AppData\Local\Autodesk\3dsMax\20xx - 64bit\ENU`):  
   ```maxscript
   python.Execute "filePath = u'[PATH TO PLUGINFOLDER]/MS_API.py'; exec(open(filePath).read(), {'__file__': filePath})"
   ```
3. **Overwrite the .py files** in the plugin folder with the ones from this repo.  
4. **Configure Quixel Bridge** to connect to 3ds Max and set download/export settings.  
5. **Export a material** – it should work with the latest OctaneRender.
