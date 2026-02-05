// index.js
const fs = require("fs");
const path = require("path");
const cron = require("node-cron");
const {
  Client,
  GatewayIntentBits,
  REST,
  Routes,
  SlashCommandBuilder,
} = require("discord.js");

const TOKEN = process.env.DISCORD_TOKEN;
const CLIENT_ID = process.env.CLIENT_ID;
const GUILD_ID = process.env.GUILD_ID; // 開発中は入れるの推奨（未設定ならグローバル登録）

if (!TOKEN || !CLIENT_ID) {
  console.error("Missing env: DISCORD_TOKEN / CLIENT_ID");
  process.exit(1);
}

const SETTINGS_PATH = path.join(__dirname, "settings.json");

function loadSettings() {
  try {
    return JSON.parse(fs.readFileSync(SETTINGS_PATH, "utf8"));
  } catch {
    return {}; // { [guildId]: { enabled: boolean, channelId: string } }
  }
}
function saveSettings(s) {
  fs.writeFileSync(SETTINGS_PATH, JSON.stringify(s, null, 2), "utf8");
}

const client = new Client({
  intents: [GatewayIntentBits.Guilds], // スラッシュコマンドだけならこれでOK
});

const commands = [
  new SlashCommandBuilder()
    .setName("remind")
    .setDescription("毎日18:50のリマインドをON/OFFします")
    .addSubcommand((sub) =>
      sub
        .setName("on")
        .setDescription("リマインドをON（このチャンネルに送信）")
    )
    .addSubcommand((sub) =>
      sub.setName("off").setDescription("リマインドをOFF")
    )
    .addSubcommand((sub) =>
      sub.setName("status").setDescription("現在の設定を表示")
    )
    .toJSON(),
];

async function registerCommands() {
  const rest = new REST({ version: "10" }).setToken(TOKEN);
  if (GUILD_ID) {
    await rest.put(Routes.applicationGuildCommands(CLIENT_ID, GUILD_ID), {
      body: commands,
    });
    console.log("Registered guild commands");
  } else {
    await rest.put(Routes.applicationCommands(CLIENT_ID), { body: commands });
    console.log("Registered global commands (反映に時間がかかることがあります)");
  }
}

client.once("ready", () => {
  console.log(`Logged in as ${client.user.tag}`);

  // 毎日18:50（日本時間）に実行
  cron.schedule(
    "* * * * *",
    async () => {
      const settings = loadSettings();
      for (const [guildId, conf] of Object.entries(settings)) {
        if (!conf.enabled || !conf.channelId) continue;

        try {
          const channel = await client.channels.fetch(conf.channelId);
          if (!channel || !channel.isTextBased()) continue;

          await channel.send("⏰ リマインド：時間です！");
        } catch (e) {
          console.error("send failed:", guildId, e?.message ?? e);
        }
      }
    },
    { timezone: "Asia/Tokyo" }
  );
});

client.on("interactionCreate", async (interaction) => {
  if (!interaction.isChatInputCommand()) return;
  if (interaction.commandName !== "remind") return;

  const sub = interaction.options.getSubcommand();
  const guildId = interaction.guildId;

  // Interaction は3秒制限があるので、軽い処理でも早めに返す癖が安全 :contentReference[oaicite:4]{index=4}
  await interaction.deferReply({ ephemeral: true });

  const settings = loadSettings();
  settings[guildId] ??= { enabled: false, channelId: null };

  if (sub === "on") {
    settings[guildId].enabled = true;
    settings[guildId].channelId = interaction.channelId; // “このチャンネル”に固定
    saveSettings(settings);
    return interaction.editReply(
      `ONにしました。毎日18:50に <#${interaction.channelId}> へ投稿します。`
    );
  }

  if (sub === "off") {
    settings[guildId].enabled = false;
    saveSettings(settings);
    return interaction.editReply("OFFにしました。");
  }

  if (sub === "status") {
    const conf = settings[guildId];
    if (!conf || !conf.channelId) return interaction.editReply("未設定です。");
    return interaction.editReply(
      `状態: ${conf.enabled ? "ON" : "OFF"} / 投稿先: <#${conf.channelId}>`
    );
  }
});

(async () => {
  await registerCommands();
  await client.login(TOKEN);
})();
