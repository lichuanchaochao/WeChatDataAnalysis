// Personal / Local Dual-Platform HD build profile.
const original = require('./package.json').build;

const win = {
  ...original.win,
  forceCodeSigning: false,
  signAndEditExecutable: false,
};
delete win.signtoolOptions;
delete win.signExts;

const mac = {
  ...original.mac,
  identity: null,
  sign: null,
  hardenedRuntime: false,
  gatekeeperAssess: false,
  target: ['dmg', 'zip'],
};

module.exports = {
  ...original,
  appId: 'local.wechatdataanalysis.hd',
  productName: 'WeChatDataAnalysis-HD',
  artifactName: process.platform === 'darwin'
    ? 'WeChatDataAnalysis-HD-mac-${arch}.${ext}'
    : 'WeChatDataAnalysis-2.6.0-HD2-Setup.${ext}',
  extraMetadata: {
    name: 'wechat-data-analysis-hd',
    version: '2.6.0-hd.2',
    localImageQualityBuild: true,
  },
  publish: null,
  win,
  mac,
  nsis: {
    oneClick: false,
    allowToChangeInstallationDirectory: true,
    deleteAppDataOnUninstall: false,
    runAfterFinish: false,
    installerIcon: original.nsis?.installerIcon,
    uninstallerIcon: original.nsis?.uninstallerIcon,
  },
};
