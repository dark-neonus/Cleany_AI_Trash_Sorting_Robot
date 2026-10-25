# Recording a demo for README.md

The root README has a spot for a demo right after the title: a reader understands what the
robot does in five seconds instead of reading the whole README.

1. Run the pipeline with recording on (someone next to the arm):

   ```bash
   scripts/run/run_pipeline.sh --recording true --max-velocity 60 --display
   ```

   After the run, `recordings/pipeline_<timestamp>/showcase.mp4` holds the front view with
   the YOLO boxes and the running model, and the wrist view in a corner.

2. Cut a short piece (10–20 s, one item sorted) into a GIF small enough for GitHub (< 10 MB):

   ```bash
   ffmpeg -ss 5 -t 15 -i recordings/pipeline_<timestamp>/showcase.mp4 \
     -vf "fps=10,scale=640:-1:flags=lanczos,split[a][b];[a]palettegen[p];[b][p]paletteuse" \
     results/demo/demo.gif
   ```

3. Commit `results/demo/demo.gif` and reference it in the README's Demo section:

   ```markdown
   ![The arm sorting a can into the metal bin](results/demo/demo.gif)
   ```

A longer video belongs on YouTube or in the Hub dataset of the run, linked from the README.
