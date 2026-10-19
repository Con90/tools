# Filming checklist

The software can't fix a bad video. Ten minutes here saves hours of chasing
noise. Print this or keep it on your phone at the trainer.

## 1. Bike

- [ ] Bike on the trainer, **level**. Most trainers hold the rear axle higher or
      lower than a wheel would. Put a riser block or a book under the front
      wheel until both axles are the same height off the floor.
- [ ] Note your current saddle height (centre of the crank axle to the top of
      the saddle, along the seat tube) so you can track changes.

## 2. Camera

- [ ] Phone on a tripod, **landscape**.
- [ ] On the **drive side** (chain side). The rider faces right in the picture.
- [ ] Lens at **crank-axle height**, **3–4 m** away. If your phone has a 2×/3×
      lens, use it: more distance means less perspective distortion.
- [ ] **Square to the bike.** Both wheels should look like circles, not
      ellipses. With the cranks horizontal, the far pedal hides behind the near
      one.
- [ ] **Level.** Use the phone's grid/level overlay. A tilted camera shifts the
      torso angle one-for-one.
- [ ] Frame head to toe and handlebar to rear wheel, with a little margin. The
      rider should fill most of the frame height. Don't move or zoom the camera
      during the clip.
- [ ] **1080p at 60 fps** (120 fps is fine too). Tap and hold to lock focus and
      exposure. Turn off any "action" or cinematic stabilisation that crops or
      warps the picture.

## 3. Light and clothing

- [ ] Light the rider evenly from the camera side. **No bright window behind
      the rider**, as backlight is the main cause of lost joints.
- [ ] Plain background that contrasts with your kit, if you can.
- [ ] Tight shorts and short sleeves so knees, hips and elbows are visible. No
      baggy clothing.
- [ ] Optional but useful: bright round stickers (15–20 mm) on the bony points
      of the near side: hip (greater trochanter), outside of the knee, ankle
      bone, outside of the shoe at the ball of the foot, shoulder, elbow, wrist.
      The pose model doesn't need them, but they make it easy to see in the
      overlay video whether the skeleton is on target, and to measure by hand.

## 4. Riding

- [ ] Warm up for 10 minutes first. Your position changes as you loosen up.
- [ ] Record **60 seconds** seated, hands on the hoods, at a steady endurance
      effort and your normal cadence (85–95 rpm). Look ahead, not at the camera.
- [ ] Optional extra clips: in the drops; at a harder effort. Analyse each
      separately.

## 5. Measure your leg (once)

- [ ] Standing straight, shoes off: measure from the bony bump on the side of
      your hip (greater trochanter) down to your outer ankle bone (lateral
      malleolus). Do it twice and average. This is `--leg-mm`, and it turns
      angles into millimetres.

## 6. Run it

```bash
./run.sh analyze my_clip.mp4 --leg-mm 880 --start 5
```

`--start 5` skips the first 5 seconds of getting settled.

## 7. Check before you trust it

- [ ] **Watch `overlay.mp4` first.** If the amber skeleton doesn't sit on your
      joints (especially hip, knee and ankle), the numbers are wrong. Re-film
      with better light or framing.
- [ ] **First time only: check one angle by hand.** Pause the video at the
      bottom of a stroke and measure the hip–knee–ankle angle yourself, with
      [Kinovea](https://www.kinovea.org/) (free) or a protractor on screen. It
      should agree with the report within about 3°. If it doesn't, the
      model is misplacing a joint on your footage: tell me, don't adjust the
      bike.

## 8. After a change

Change one thing, ride it for a few days, re-film the same way, then:

```bash
./run.sh compare output/<before-folder> output/<after-folder>
```
